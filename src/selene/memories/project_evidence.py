"""Local source validation for project-bound durable decisions."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from selene.context.model import SourceReference
from selene.context.sources import ContextSources
from selene.memories.evidence import (
    MemoryAssessment,
    MemoryDocument,
    MemoryEvidenceIssue,
    MemoryEvidenceRequest,
    MemoryProvenance,
)
from selene.util.cancellation import CancellationToken

if TYPE_CHECKING:
    from selene.project import Project


class ProjectMemoryEvidence:
    """Validate local source versions without generating summaries or fetching remote references."""

    def __init__(self, project: "Project"):
        self._project = project

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _expiration(value: str | None) -> datetime | None:
        if value is None:
            return None
        expiry = datetime.fromisoformat(value)
        if expiry.tzinfo is None:
            raise ValueError("Memory expiration must include a timezone")
        return expiry

    def _binding(self) -> str:
        scope = self._project.get_local_index().scope
        scope.validate_root()
        metadata = scope.root.stat()
        value = (str(scope.root), metadata.st_dev, metadata.st_ino)
        return hashlib.sha256(json.dumps(value).encode("utf-8")).hexdigest()

    def require_memory_path(self, path: str) -> None:
        scope = self._project.get_local_index().scope
        scope.validate_root()
        relative = Path(path).absolute().relative_to(Path(self._project.project_root).absolute())
        candidate = scope.root / relative
        canonical = candidate.resolve(strict=False)
        if not canonical.is_relative_to(scope.root) or canonical != candidate:
            raise ValueError("Evidence-backed memories require a canonical path inside the active project without symlink aliases")

    def _source_issues(self, references: tuple[SourceReference, ...], prefix: str) -> tuple[MemoryEvidenceIssue, ...]:
        index = self._project.get_local_index()
        observation = index.refresh()
        sources = ContextSources(index, observation, self._project.project_config.encoding, max_files=16)
        issues = []
        for reference in references:
            CancellationToken.check_current()
            try:
                path = index.scope.normalize(reference.path)
                if path != reference.path or (prefix and path != prefix and not path.startswith(prefix + "/")):
                    issues.append(MemoryEvidenceIssue("outside_declared_scope", reference.path))
                    continue
                if not sources.contains(path):
                    issues.append(MemoryEvidenceIssue("source_missing_excluded_or_not_searchable", path, reference.sha256))
                    continue
                document = sources.read(path)
                if document.sha256 != reference.sha256:
                    issues.append(MemoryEvidenceIssue("source_changed", path, reference.sha256, document.sha256))
                    continue
                if document.canonical_path != path:
                    issues.append(MemoryEvidenceIssue("source_alias_requires_canonical_path", path, reference.sha256))
                    continue
                document.reference(reference.start_line, reference.end_line, reference.symbol)
            except (OSError, ValueError, RuntimeError) as error:
                issues.append(MemoryEvidenceIssue("source_unavailable_or_invalid_range:" + type(error).__name__, reference.path))
        # recheck participating hashes after capture without invalidating on unrelated index changes
        current = index.refresh()
        for reference in references:
            if any(issue.path == reference.path for issue in issues):
                continue
            entry = current.files.get(reference.path)
            try:
                if entry is None or entry.sha256 != reference.sha256 or index.scope.fingerprint(reference.path) != reference.sha256:
                    issues.append(MemoryEvidenceIssue("source_changed_during_assessment", reference.path, reference.sha256))
            except (OSError, ValueError, RuntimeError):
                issues.append(MemoryEvidenceIssue("source_unavailable_during_assessment", reference.path, reference.sha256))
        return tuple(issues)

    def capture(self, content: str, request: MemoryEvidenceRequest) -> MemoryProvenance:
        if not 1 <= len(content) <= MemoryDocument.MAX_CONTENT_CHARS:
            raise ValueError("A durable decision must contain between one and 16000 characters")
        if not 1 <= len(request.owner) <= 200 or any(ord(character) < 32 for character in request.owner):
            raise ValueError("Provide a nonempty owner declaration without control characters, at most 200 characters")
        if request.origin not in {"observation", "decision", "human_decision"}:
            raise ValueError("Unsupported memory origin")
        if not 0 <= len(request.evidence) <= 16 or (not request.evidence and request.origin != "human_decision"):
            raise ValueError("Provide one to sixteen source references, or explicitly declare a human decision without source evidence")
        scope = self._project.get_local_index().scope.normalize(request.scope)
        self._expiration(request.expires_at)
        issues = self._source_issues(request.evidence, scope) if request.evidence else ()
        if issues:
            raise ValueError("Memory evidence is not current: " + json.dumps([asdict(issue) for issue in issues]))
        return MemoryProvenance(
            1,
            self._binding(),
            request.owner,
            request.evidence,
            scope,
            request.origin,
            MemoryDocument.sha256(content),
            self._now(),
            request.expires_at,
        )

    def assess(self, document: MemoryDocument, raw: str) -> MemoryAssessment:
        provenance = document.provenance
        body_hash = MemoryDocument.sha256(document.content)
        raw_hash = MemoryDocument.sha256(raw)
        checked_at = self._now()
        if provenance is None:
            return MemoryAssessment(
                "unverified", (MemoryEvidenceIssue("legacy_memory_without_provenance"),), checked_at, raw_hash, body_hash, None
            )
        if provenance.project_binding != self._binding():
            return MemoryAssessment("scope_mismatch", (), checked_at, raw_hash, body_hash, None)
        issues = []
        if provenance.content_sha256 != body_hash:
            issues.append(MemoryEvidenceIssue("memory_content_changed_since_recording"))
        try:
            expiry = self._expiration(provenance.expires_at)
            if expiry is not None and expiry <= datetime.now(UTC):
                issues.append(MemoryEvidenceIssue("record_expired"))
        except ValueError:
            issues.append(MemoryEvidenceIssue("invalid_expiration"))
        issues.extend(self._source_issues(provenance.evidence, provenance.scope) if provenance.evidence else ())
        if not provenance.evidence:
            issues.append(MemoryEvidenceIssue("declared_decision_without_source_evidence"))
        reasons = {issue.reason for issue in issues}
        if "memory_content_changed_since_recording" in reasons:
            status = "needs_review"
        elif "record_expired" in reasons:
            status = "expired"
        elif any(issue.path or issue.reason == "invalid_expiration" for issue in issues):
            status = "stale"
        elif not provenance.evidence:
            status = "unverified"
        else:
            status = "current"
        return MemoryAssessment(status, tuple(issues), checked_at, raw_hash, body_hash, provenance)
