"""Recover file operations from durable intents and observed inode placement."""

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from selene.changes.model import ChangeConflict, ChangeInputError
from selene.edit_plans.filesystem import AtomicRename, FileState, PlanDirectory
from selene.edit_plans.journal import PlanJournal
from selene.edit_plans.model import EntryResult, PlanEntry, PlanManifest, StepIntent
from selene.util.cancellation import CancellationToken


class ChangeExecutionObserver(Protocol):
    """Observe completed, synced file operations without changing their recovery semantics."""

    def after_file(self, path: str, direction: str) -> None: ...


class NullChangeExecutionObserver:
    def after_file(self, path: str, direction: str) -> None:
        pass


@dataclass(frozen=True)
class ObservedStep:
    ran: bool
    target: FileState | None
    slot: FileState | None


class PlanExecution:
    """Apply at most one forward and one reverse operation per file, retaining all displaced inodes."""

    def __init__(self, root: PlanDirectory, journal: PlanJournal, manifest: PlanManifest, observer: ChangeExecutionObserver):
        self._root = root
        self._journal = journal
        self._manifest = manifest
        self._observer = observer
        self._rename = AtomicRename()

    @staticmethod
    def _same(left: FileState | None, right: FileState | None) -> bool:
        return (left is None and right is None) or (left is not None and left.same_inode(right))

    def _observe(self, intent: StepIntent, parent: PlanDirectory, name: str) -> ObservedStep:
        target = parent.state(name)
        slot = self._journal.directory.state(f"slot-{intent.entry}")
        if self._same(slot, intent.slot_before):
            return ObservedStep(False, target, slot)
        if intent.exchange:
            if self._same(target, intent.slot_before) or self._same(slot, intent.target_before):
                return ObservedStep(True, target, slot)
        elif intent.target_before is None:
            if slot is None:
                return ObservedStep(True, target, slot)
        elif slot is not None:
            return ObservedStep(True, target, slot)
        raise ChangeConflict("File placement is ambiguous; retained versions require manual recovery")

    def _parent(self, entry: PlanEntry, parent: PlanDirectory) -> None:
        if parent.identity != (entry.parent_device, entry.parent_inode):
            raise ChangeConflict(f"Parent directory identity changed: {entry.path}")
        parent.verify_parent(self._root, entry.path)

    def _intent(self, index: int, entry: PlanEntry, parent: PlanDirectory, direction: Literal["apply", "rollback"]) -> StepIntent:
        target = parent.state(Path(entry.path).name)
        slot = self._journal.directory.state(f"slot-{index}")
        if direction == "apply":
            if target != entry.before or slot != entry.staged:
                raise ChangeConflict("Source or staged content no longer matches the prepared version; prepare a new plan")
        else:
            if target != entry.staged:
                raise ChangeConflict("The applied file changed externally; rollback would replace that edit")
            if (slot is None) != (entry.before is None):
                raise ChangeConflict("The displaced file is unavailable; manual recovery is required")
        if target is not None and target.mode & 0o222 == 0:
            raise PermissionError("The target file has no write permission bits")
        return StepIntent(direction, index, target, slot, target is not None and slot is not None)

    def _run(self, intent: StepIntent, parent: PlanDirectory, name: str) -> None:
        # retain an intent before the indivisible name operation; never overwrite an existing slot
        observed = self._observe(intent, parent, name)
        if observed.ran:
            return
        if observed.target != intent.target_before or observed.slot != intent.slot_before:
            raise ChangeConflict("A file changed after the durable intent was prepared")
        CancellationToken.check_current()
        slot = f"slot-{intent.entry}"
        if intent.exchange:
            self._rename.move(parent.fd, name, self._journal.directory.fd, slot, exchange=True)
        elif intent.target_before is None:
            self._rename.move(self._journal.directory.fd, slot, parent.fd, name, exchange=False)
        else:
            self._rename.move(parent.fd, name, self._journal.directory.fd, slot, exchange=False)
        os.fsync(parent.fd)
        os.fsync(self._journal.directory.fd)

    def _result(self, index: int, entry: PlanEntry, parent: PlanDirectory) -> EntryResult:
        name = Path(entry.path).name
        target = parent.state(name)
        slot = self._journal.directory.state(f"slot-{index}")
        sha256 = None if target is None else target.sha256
        retained = None if slot is None else slot.sha256
        reverse = self._journal.load_intent(index, "rollback")
        forward = self._journal.load_intent(index, "apply")
        if reverse is not None and self._observe(reverse, parent, name).ran:
            expected_target, expected_slot = reverse.slot_before, reverse.target_before
            status = "rolled_back"
        elif forward is not None and self._observe(forward, parent, name).ran:
            expected_target, expected_slot = entry.staged, entry.before
            status = "applied"
        else:
            expected_target, expected_slot = entry.before, entry.staged
            status = "pending"
        if target != expected_target or slot != expected_slot:
            return EntryResult(
                entry.path, "conflict", sha256, retained, "Observed content or identity differs; all retained versions remain available"
            )
        return EntryResult(entry.path, status, sha256, retained)

    def inspect(self) -> tuple[EntryResult, ...]:
        results = []
        for index, entry in enumerate(self._manifest.entries):
            try:
                with self._root.parent(entry.path) as parent:
                    self._parent(entry, parent)
                    results.append(self._result(index, entry, parent))
            except (OSError, ValueError, RuntimeError) as error:
                results.append(EntryResult(entry.path, "conflict", None, None, str(error)))
        return tuple(results)

    def execute(self, direction: Literal["apply", "rollback"]) -> tuple[EntryResult, ...]:
        # reject stale participants before the first forward mutation and preserve unrelated paths
        initial = self.inspect()
        if direction == "apply":
            if any(item.status in {"conflict", "rolled_back"} for item in initial):
                return initial
            if any(self._journal.load_intent(index, "rollback") is not None for index in range(len(self._manifest.entries))):
                raise ChangeConflict("Rollback has started; continue rollback or prepare a new plan")
            if not self._manifest.allow_syntax_errors and any(item.status == "error" for item in self._manifest.diagnostics):
                raise ChangeInputError("The prepared syntax checks failed; fix the proposal or explicitly prepare with allow_syntax_errors")
        order = range(len(self._manifest.entries)) if direction == "apply" else reversed(range(len(self._manifest.entries)))
        failure: EntryResult | None = None
        for index in order:
            CancellationToken.check_current()
            entry = self._manifest.entries[index]
            try:
                with self._root.parent(entry.path) as parent:
                    self._parent(entry, parent)
                    name = Path(entry.path).name
                    forward = self._journal.load_intent(index, "apply")
                    if direction == "rollback" and (forward is None or not self._observe(forward, parent, name).ran):
                        continue
                    intent = self._journal.load_intent(index, direction)
                    if intent is None:
                        intent = self._intent(index, entry, parent, direction)
                        self._journal.save_intent(intent)
                    if intent.direction != direction or intent.entry != index:
                        raise ChangeConflict("Recovery intent has an invalid entry or direction")
                    self._run(intent, parent, name)
                    self._parent(entry, parent)
                    self._observer.after_file(entry.path, direction)
                    result = self._result(index, entry, parent)
                    if result.status == "conflict":
                        failure = result
                        break
            except (OSError, ValueError, RuntimeError) as error:
                failure = EntryResult(entry.path, "conflict" if isinstance(error, ChangeConflict) else "failed", None, None, str(error))
                break
        results = list(self.inspect())
        if failure is not None:
            results = [
                replace(item, status=failure.status, reason=failure.reason) if item.path == failure.path else item for item in results
            ]
        return tuple(results)
