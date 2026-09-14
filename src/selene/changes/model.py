"""Source preconditions and materialized, unapplied text changes."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ProposedFileChange:
    """A complete replacement, deletion or creation with an explicit source precondition.

    A null expected hash means the path must not exist. A null content means deletion.
    """

    path: str
    expected_sha256: str | None
    new_content: str | None


@dataclass(frozen=True)
class ChangedRange:
    """Half-open 0-based line spans in the original and proposed source."""

    old_start: int
    old_end: int
    new_start: int
    new_end: int


@dataclass(frozen=True)
class MaterializedFileChange:
    path: str
    canonical_path: str
    kind: Literal["create", "modify", "delete"]
    expected_sha256: str | None
    proposed_sha256: str | None
    old_content: str | None
    new_content: str | None
    ranges: tuple[ChangedRange, ...]


class ChangeInputError(ValueError):
    """A proposed change is malformed or outside the supported input limits."""


class ChangeConflict(ValueError):
    """The current project source does not satisfy a proposed change's preconditions."""
