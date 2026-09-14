"""Human-readable memory provenance and explicit, derived freshness assessments."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from selene.context.model import SourceReference


@dataclass(frozen=True)
class MemoryEvidenceRequest:
    """Client-authored provenance; owner and origin are declarations, not authenticated identities."""

    owner: str
    evidence: tuple[SourceReference, ...]
    scope: str = ""
    origin: Literal["observation", "decision", "human_decision"] = "decision"
    expires_at: str | None = None


@dataclass(frozen=True)
class MemoryProvenance:
    version: int
    project_binding: str
    owner: str
    evidence: tuple[SourceReference, ...]
    scope: str
    origin: Literal["observation", "decision", "human_decision"]
    content_sha256: str
    recorded_at: str
    expires_at: str | None = None


@dataclass(frozen=True)
class MemoryEvidenceIssue:
    reason: str
    path: str = ""
    expected_sha256: str | None = None
    current_sha256: str | None = None


@dataclass(frozen=True)
class MemoryAssessment:
    status: Literal["current", "stale", "needs_review", "expired", "scope_mismatch", "unverified"]
    issues: tuple[MemoryEvidenceIssue, ...]
    checked_at: str
    memory_sha256: str
    content_sha256: str
    provenance: MemoryProvenance | None


@dataclass(frozen=True)
class MemoryDocument:
    """A Markdown body with an optional single-file JSON provenance header."""

    content: str
    provenance: MemoryProvenance | None = None

    _PREFIX = "<!-- selene-evidence:v1\n"
    _END = "\n-->\n"
    MAX_CONTENT_CHARS = 16000
    MAX_HEADER_BYTES = 32768
    MAX_PREFIX_CHARS = 4096

    @staticmethod
    def sha256(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _json(value: object, *, indent: int | None = None) -> str:
        return json.dumps(value, ensure_ascii=True, indent=indent).replace("<", "\\u003c").replace(">", "\\u003e")

    @classmethod
    def has_provenance(cls, raw: str) -> bool:
        return raw.lstrip("\ufeff \t\r\n").startswith("<!-- selene-evidence:")

    @classmethod
    def parse(cls, raw: str) -> "MemoryDocument":
        if not cls.has_provenance(raw):
            return cls(raw)
        stripped = raw.lstrip("\ufeff \t\r\n")
        if len(raw) - len(stripped) > cls.MAX_PREFIX_CHARS:
            raise ValueError("Memory provenance has an oversized leading prefix")
        raw = stripped
        if not raw.startswith((cls._PREFIX, cls._PREFIX.replace("\n", "\r\n"))):
            raise ValueError("Unsupported memory provenance format; review the raw memory file")
        prefix = cls._PREFIX
        ending = cls._END
        if raw.startswith(prefix.replace("\n", "\r\n")):
            prefix = prefix.replace("\n", "\r\n")
            ending = ending.replace("\n", "\r\n")
        end = raw.find(ending, len(prefix))
        if end == -1 or len(raw[:end].encode("utf-8")) > cls.MAX_HEADER_BYTES:
            raise ValueError("Malformed or oversized memory provenance header")
        data = json.loads(raw[len(prefix) : end])
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported memory provenance version")
        try:
            evidence = tuple(SourceReference(**value) for value in data.pop("evidence"))
            provenance = MemoryProvenance(**data, evidence=evidence)
            if len(evidence) > 16:
                raise ValueError("A memory may reference at most sixteen sources")
            hashes = (provenance.project_binding, provenance.content_sha256, *(reference.sha256 for reference in evidence))
            if any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes):
                raise ValueError("Memory provenance requires canonical SHA-256 digests")
            if not isinstance(provenance.owner, str) or not 1 <= len(provenance.owner) <= 200:
                raise ValueError("Invalid memory owner declaration")
            if provenance.origin not in {"observation", "decision", "human_decision"}:
                raise ValueError("Invalid memory origin")
            if not isinstance(provenance.scope, str) or not isinstance(provenance.recorded_at, str):
                raise ValueError("Invalid memory scope or recording time")
        except (KeyError, TypeError) as error:
            raise ValueError("Malformed memory provenance fields") from error
        content = raw[end + len(ending) :]
        if len(content) > cls.MAX_CONTENT_CHARS:
            raise ValueError("Evidence-backed memory content exceeds 16000 characters")
        return cls(content, provenance)

    def serialize(self) -> str:
        if self.provenance is None:
            return self.content
        if len(self.content) > self.MAX_CONTENT_CHARS:
            raise ValueError("An evidence-backed memory may contain at most 16000 content characters")
        header = self._PREFIX + self._json(asdict(self.provenance), indent=2) + self._END
        if len(header.encode("utf-8")) > self.MAX_HEADER_BYTES:
            raise ValueError("Memory provenance exceeds the 32 KiB header allowance")
        return header + self.content

    def render(self, assessment: MemoryAssessment) -> str:
        """Present freshness before the claim; never supply a foreign project's body automatically."""
        if self.provenance is None:
            return self.content
        if assessment.status == "scope_mismatch":
            return "Memory evidence status: scope_mismatch. This record belongs to another project binding; its content is withheld."
        if assessment.provenance is None:
            return "Memory evidence status: unverified. Project scope or evidence could not be established; content is withheld."
        metadata = {
            "status": assessment.status,
            "issues": [asdict(issue) for issue in assessment.issues],
            "memory_sha256": assessment.memory_sha256,
            "owner": self.provenance.owner,
            "origin": self.provenance.origin,
            "scope": self.provenance.scope,
            "recorded_at": self.provenance.recorded_at,
            "expires_at": self.provenance.expires_at,
            "evidence": [asdict(reference) for reference in self.provenance.evidence],
        }
        return (
            "Memory evidence assessment (source-version checks; claim correctness and declared ownership are not verified):\n```json\n"
            + self._json(metadata)
            + "\n```\n\n"
            + self.content
        )


@dataclass(frozen=True)
class MemoryEditingView:
    content: str
    assessment: MemoryAssessment
    has_provenance: bool


class MemoryEvidenceEvaluator(Protocol):
    """Bind memory provenance and supporting sources to the active project."""

    def require_memory_path(self, path: str) -> None: ...

    def capture(self, content: str, request: MemoryEvidenceRequest) -> MemoryProvenance: ...

    def assess(self, document: MemoryDocument, raw: str) -> MemoryAssessment: ...
