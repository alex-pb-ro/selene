"""Project-bound, expiring context plans and exact-budget JSON pages."""

import json
import math
import secrets
import threading
import time
import weakref
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from selene.context.model import ContextAnchor, ContextCandidate, ContextEvidence, ContextRole, ContextSourceVersion, SourceReference
from selene.context.selection import ContextSelector
from selene.context.semantic import LanguageServerContextProvider
from selene.context.sources import ContextSources
from selene.util.cancellation import CancellationToken

if TYPE_CHECKING:
    from selene.project import Project


@dataclass(frozen=True)
class ContextPlan:
    """Selection metadata only; source bodies are re-read for every requested page."""

    identifier: str
    created_at: float
    generation: int
    candidates: tuple[ContextCandidate, ...]
    versions: tuple[ContextSourceVersion, ...]
    limitations: tuple[str, ...]
    semantic_calls: int


@dataclass
class ContextPageItem:
    id: str
    source: SourceReference
    canonical_path: str
    roles: tuple[ContextRole, ...]
    evidence: tuple[ContextEvidence, ...]
    content: str | None = None
    body_status: str = "omitted"
    shown_end_line: int | None = None


class ContextPageRenderer:
    """Serialize context within a character budget including its own metadata."""

    @staticmethod
    def _serialize(payload: dict, max_chars: int) -> str:
        payload["budget"] = {"unit": "json_characters", "limit": max_chars, "used": 0}
        for _ in range(8):
            result = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=asdict)
            size = len(result)
            if payload["budget"]["used"] == size:
                return result
            payload["budget"]["used"] = size
        raise RuntimeError("Could not determine the serialized context budget")

    @classmethod
    def render(
        cls,
        plan: ContextPlan,
        sources: ContextSources,
        *,
        offset: int,
        max_chars: int,
        include_bodies: bool,
        selected_ids: tuple[int, ...] | None = None,
    ) -> str:
        if not 2048 <= max_chars <= 100000:
            raise ValueError("Context output budgets must be between 2048 and 100000 JSON characters")
        indices = list(range(offset, len(plan.candidates))) if selected_ids is None else list(selected_ids)
        payload = {
            "bundle_id": plan.identifier,
            "selection_generation": plan.generation,
            "index_observed_at": sources.observation.status.observed_at,
            "index_reconciled_at": sources.observation.status.reconciled_at,
            "index_mode": sources.observation.status.watcher,
            "source_file_count": len(plan.versions),
            "available_items": len(plan.candidates),
            "semantic_operations": plan.semantic_calls,
            "limitations": plan.limitations,
            "items": [],
            "continuation": None,
            "remaining_items": 0,
        }
        items = []
        for position, item_index in enumerate(indices):
            CancellationToken.check_current()
            candidate = plan.candidates[item_index]
            reference = candidate.reference
            document = sources.read(reference.path)
            item = ContextPageItem(str(item_index), reference, candidate.canonical_path, candidate.roles, candidate.evidence)
            if include_bodies:
                # allocate room for several roles; a body request can use a larger per-item slice
                line_limit = 500 if selected_ids is not None else 40
                end_line = min(reference.end_line, reference.start_line + line_limit - 1)
                lines = document.lines[reference.start_line - 1 : end_line]
                body_limit = max_chars // max(2, min(4, len(indices)))
                while lines and len("\n".join(lines)) > body_limit:
                    lines = lines[:-1]
                item.content = "\n".join(lines)
                item.shown_end_line = reference.start_line + len(lines) - 1 if lines else None
                item.body_status = "complete" if item.shown_end_line == reference.end_line else "partial"
            pending = len(indices) - position - 1
            continuation = f"{plan.identifier}.{item_index + 1}" if pending and selected_ids is None else None
            payload.update(items=items + [item], continuation=continuation, remaining_items=pending)
            result = cls._serialize(payload, max_chars)
            while len(result) > max_chars and item.content:
                lines = item.content.split("\n")[:-1]
                item.content = "\n".join(lines)
                item.shown_end_line = reference.start_line + len(lines) - 1 if lines else None
                item.body_status = "partial"
                result = cls._serialize(payload, max_chars)
            if len(result) > max_chars:
                if not items:
                    raise ValueError(f"Context metadata needs a larger output budget (at least {len(result)} characters)")
                if selected_ids is not None:
                    raise ValueError("The selected item metadata does not fit; request fewer items or a larger budget")
                payload.update(items=items, continuation=f"{plan.identifier}.{item_index}", remaining_items=len(indices) - position)
                result = cls._serialize(payload, max_chars)
                if len(result) > max_chars:
                    raise ValueError("The continuation metadata needs a larger output budget")
                return result
            items.append(item)
        payload.update(items=items, continuation=None, remaining_items=0)
        result = cls._serialize(payload, max_chars)
        if len(result) > max_chars:
            raise ValueError("Context coverage metadata exceeds the requested output budget")
        return result


class ContextBundleService:
    """Keep a bounded set of project-local context plans; never persist source bodies."""

    def __init__(self, project: "Project", *, max_plans: int = 8, ttl_seconds: float = 300.0):
        if max_plans < 1 or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("Context plan capacity and lifetime must be positive and finite")
        self._project_ref = weakref.ref(project)
        self._max_plans = max_plans
        self._ttl = ttl_seconds
        self._plans: OrderedDict[str, ContextPlan] = OrderedDict()
        self._lock = threading.RLock()
        self._closed = False

    @property
    def _project(self) -> "Project":
        project = self._project_ref()
        if project is None or self._closed:
            raise ValueError("The project context service is closed")
        return project

    def _sources(self) -> ContextSources:
        project = self._project
        index = project.get_local_index()
        return ContextSources(index, index.refresh(), project.project_config.encoding)

    def _lookup(self, identifier: str) -> ContextPlan:
        if len(identifier) > 64:
            raise ValueError("Unknown or expired context bundle for this project")
        cutoff = time.monotonic() - self._ttl
        self._plans = OrderedDict((key, plan) for key, plan in self._plans.items() if plan.created_at >= cutoff)
        plan = self._plans.get(identifier)
        if plan is None:
            raise ValueError("Unknown or expired context bundle for this project")
        self._plans.move_to_end(identifier)
        return plan

    def _validate_plan(self, plan: ContextPlan, sources: ContextSources) -> None:
        sources.validate_versions(plan.versions, plan.generation)

    def find(
        self, query: str, anchors: tuple[ContextAnchor, ...] = (), *, scope: str = "", max_chars: int = 20000, include_bodies: bool = True
    ) -> str:
        if len(query) > 8192 or len(anchors) > 8:
            raise ValueError("Use at most 8192 query characters and eight anchors")
        if not query.strip():
            query = " ".join(anchor.symbol or anchor.path for anchor in anchors)
        if not query.strip():
            raise ValueError("Provide a query or an explicit source anchor")
        with self._lock:
            self._project.ls_sync_file_system_changes()
            sources = self._sources()
            semantics = LanguageServerContextProvider(self._project, sources)
            selector = ContextSelector(sources, semantics, scope)
            candidates = selector.select(query, anchors)
            sources.validate()
            limitations = selector.limitations()
            if sources.observation.status.issues:
                limitations += ("project_scope_issues_reported_by_index",)
            plan = ContextPlan(
                secrets.token_urlsafe(18),
                time.monotonic(),
                sources.observation.status.generation,
                candidates,
                sources.versions(),
                limitations,
                semantics.calls_used(),
            )
            result = ContextPageRenderer.render(plan, sources, offset=0, max_chars=max_chars, include_bodies=include_bodies)
            sources.validate()
            self._plans[plan.identifier] = plan
            while len(self._plans) > self._max_plans:
                self._plans.popitem(last=False)
            return result

    def continue_bundle(self, continuation: str, *, max_chars: int = 20000, include_bodies: bool = True) -> str:
        with self._lock:
            identifier, separator, raw_offset = continuation.rpartition(".")
            if not separator or not raw_offset.isdecimal() or len(raw_offset) > 8:
                raise ValueError("Invalid context continuation")
            plan = self._lookup(identifier)
            offset = int(raw_offset)
            if not 0 <= offset < len(plan.candidates):
                raise ValueError("Invalid context continuation offset")
            sources = self._sources()
            self._validate_plan(plan, sources)
            result = ContextPageRenderer.render(plan, sources, offset=offset, max_chars=max_chars, include_bodies=include_bodies)
            self._validate_plan(plan, self._sources())
            return result

    def read_items(self, identifier: str, item_ids: tuple[str, ...], *, max_chars: int = 20000) -> str:
        with self._lock:
            plan = self._lookup(identifier)
            if not item_ids or len(item_ids) > 16 or len(set(item_ids)) != len(item_ids):
                raise ValueError("Select between one and sixteen distinct context item IDs")
            if any(not value.isdecimal() or len(value) > 8 for value in item_ids):
                raise ValueError("Invalid context item IDs")
            selected = tuple(int(value) for value in item_ids)
            if any(value >= len(plan.candidates) for value in selected):
                raise ValueError("Unknown context item ID")
            sources = self._sources()
            self._validate_plan(plan, sources)
            result = ContextPageRenderer.render(plan, sources, offset=0, max_chars=max_chars, include_bodies=True, selected_ids=selected)
            self._validate_plan(plan, self._sources())
            return result

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._plans.clear()
