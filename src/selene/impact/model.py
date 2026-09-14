"""Evidence and coverage records for proposed-change impact analysis."""

from dataclasses import dataclass
from typing import Literal

from selene.changes.model import ChangedRange
from selene.context.model import SourceReference


@dataclass(frozen=True)
class ChangedFileSummary:
    path: str
    kind: str
    expected_sha256: str | None
    proposed_sha256: str | None
    ranges: tuple[ChangedRange, ...]


@dataclass(frozen=True)
class ChangedSymbol:
    source: SourceReference
    mapping: Literal["overlapping_changed_lines", "adjacent_to_insertion"]


@dataclass(frozen=True)
class ImpactFinding:
    target: SourceReference
    role: str
    relationship: str
    evidence: Literal["language_server", "declared_mapping", "heuristic"]
    origin: SourceReference
    site: SourceReference
    depth: int
    via: tuple[SourceReference, ...] = ()
    site_column: int | None = None
    origin_revision: Literal["current", "proposed"] = "current"


@dataclass(frozen=True)
class ImpactUncertainty:
    reason: str
    next_step: str
    source: SourceReference | None = None
