"""Source references and evidence shared by context retrieval components."""

from dataclasses import dataclass
from typing import Literal

ContextRole = Literal["anchor", "code", "dependency", "type", "test", "documentation", "configuration", "caller"]
EvidenceStrength = Literal["requested", "language_server", "lexical", "heuristic"]


@dataclass(frozen=True)
class ContextAnchor:
    """A requested project-relative path and optional symbol name path."""

    path: str
    symbol: str = ""


@dataclass(frozen=True)
class ContextSourceVersion:
    path: str
    canonical_path: str
    sha256: str


@dataclass(frozen=True)
class SourceReference:
    """An inclusive, 1-based line range in a specific version of a project file."""

    path: str
    sha256: str
    start_line: int
    end_line: int
    symbol: str = ""

    def __post_init__(self) -> None:
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("Source ranges must be non-empty, inclusive and 1-based")


@dataclass(frozen=True)
class ContextEvidence:
    kind: str
    strength: EvidenceStrength
    origin: SourceReference | None = None
    site: SourceReference | None = None


@dataclass(frozen=True)
class ContextCandidate:
    reference: SourceReference
    canonical_path: str
    roles: tuple[ContextRole, ...]
    evidence: tuple[ContextEvidence, ...]
    priority: int


@dataclass(frozen=True)
class SemanticNode:
    """A language-server symbol with its identifier position in LSP coordinates."""

    reference: SourceReference
    kind: str
    declaration_line: int
    declaration_column: int


@dataclass(frozen=True)
class SemanticEdge:
    target: SemanticNode
    origin: SourceReference
    kind: Literal["definition_of_reference", "reference_to_symbol"]
    site: SourceReference


class StaleContextError(ValueError):
    """Source versions no longer support a prepared context selection."""


class ContextLimitReached(RuntimeError):
    """A bounded context retrieval resource is exhausted."""
