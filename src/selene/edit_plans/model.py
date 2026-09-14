"""Durable plan metadata and bounded execution results."""

from dataclasses import dataclass
from typing import Literal

from selene.changes.model import ChangedRange
from selene.edit_plans.filesystem import FileState


@dataclass(frozen=True)
class PlanEntry:
    path: str
    kind: Literal["create", "modify", "delete"]
    before: FileState | None
    proposed_sha256: str | None
    staged: FileState | None
    parent_device: int
    parent_inode: int
    ranges: tuple[ChangedRange, ...]


@dataclass(frozen=True)
class PlanDiagnostic:
    path: str
    check: str
    status: Literal["passed", "error", "not_checked"]
    message: str = ""
    line: int | None = None


@dataclass(frozen=True)
class PlanManifest:
    version: int
    nonce: str
    request_digest: str
    input_digest: str
    project_root: str
    root_device: int
    root_inode: int
    encoding: str
    allow_syntax_errors: bool
    entries: tuple[PlanEntry, ...]
    diagnostics: tuple[PlanDiagnostic, ...]


@dataclass(frozen=True)
class StepIntent:
    direction: Literal["apply", "rollback"]
    entry: int
    target_before: FileState | None
    slot_before: FileState | None
    exchange: bool


@dataclass(frozen=True)
class EntryResult:
    path: str
    status: Literal["pending", "applied", "rolled_back", "conflict", "failed"]
    current_sha256: str | None
    retained_sha256: str | None
    reason: str = ""


@dataclass(frozen=True)
class PlannedFile:
    path: str
    kind: str
    expected_sha256: str | None
    proposed_sha256: str | None
    ranges: tuple[ChangedRange, ...]


@dataclass(frozen=True)
class ExecutionPolicy:
    max_files: int = 16
    max_file_bytes: int = 2 * 1024 * 1024
    max_proposed_bytes: int = 8 * 1024 * 1024
    failure_handling: str = "stop_and_retain_for_recovery"
    file_operations: tuple[str, ...] = ("create", "modify", "delete")
    automatic_rollback: bool = False


@dataclass(frozen=True)
class PlanResult:
    plan_id: str
    status: Literal["prepared", "applied", "rolled_back", "partial", "conflict", "failed"]
    files: tuple[EntryResult, ...]
    changes: tuple[PlannedFile, ...]
    execution_policy: ExecutionPolicy
    diagnostics: tuple[PlanDiagnostic, ...]
    recovery_directory: str
    checks: tuple[str, ...]
    limitations: tuple[str, ...]
