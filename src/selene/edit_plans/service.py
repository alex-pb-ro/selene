"""Prepare, apply, inspect and roll back local source change plans."""

import ast
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from selene.changes.model import ChangeConflict, ChangedRange, ChangeInputError, MaterializedFileChange, ProposedFileChange
from selene.changes.resolver import ChangeResolver
from selene.context.sources import ContextSources
from selene.edit_plans.execution import ChangeExecutionObserver, NullChangeExecutionObserver, PlanExecution
from selene.edit_plans.filesystem import AtomicRename, FileState, PlanDirectory
from selene.edit_plans.journal import PlanJournal
from selene.edit_plans.model import ExecutionPolicy, PlanDiagnostic, PlanEntry, PlanManifest, PlannedFile, PlanResult
from selene.indexing.project_policy import ProjectIndexPolicy
from selene.util.cancellation import CancellationToken

if TYPE_CHECKING:
    from selene.project import Project


class RecoverableChanges:
    """Bound recovery operations to one project, with durable local contents and no remote calls."""

    _LIMITATIONS = (
        "Files change one at a time; external readers may observe an intermediate project state.",
        "Syntax checks do not establish type correctness, runtime behavior or passing tests.",
        "Recovery retains local original/proposed contents and displaced inodes until explicitly removed after review.",
        "Open file descriptors held by other writers can still modify displaced inodes; concurrent directory moves and power-loss guarantees are filesystem-dependent.",
    )

    def __init__(self, project: "Project", *, observer: ChangeExecutionObserver | None = None):
        self._project = project
        self._index = project.get_local_index()
        self._root = self._index.scope.root
        self._observer = observer or NullChangeExecutionObserver()

    def _validate_path(self, entry: PlanEntry) -> None:
        self._index.scope.validate_root()
        policy = ProjectIndexPolicy(self._project)
        policy.refresh()
        if not policy.includes(entry.path, directory=False):
            raise ChangeConflict(f"Changed path is now excluded: {entry.path}")
        for parent in Path(entry.path).parents:
            if not policy.includes(parent.as_posix(), directory=True):
                raise ChangeConflict(f"Changed path is below an excluded directory: {entry.path}")

    @staticmethod
    def _diagnostic(change: MaterializedFileChange) -> PlanDiagnostic:
        if change.new_content is None:
            return PlanDiagnostic(change.path, "resource_operation", "passed", "Existing file deletion")
        suffix = Path(change.path).suffix.casefold()
        check = "python_ast_current_interpreter" if suffix == ".py" else "json_parse" if suffix == ".json" else "syntax"
        try:
            if suffix == ".py":
                ast.parse(change.new_content, filename=change.path)
            elif suffix == ".json":
                json.loads(change.new_content)
            else:
                return PlanDiagnostic(change.path, check, "not_checked", "No staged syntax adapter for this file type")
            return PlanDiagnostic(change.path, check, "passed")
        except (SyntaxError, ValueError, RecursionError) as error:
            return PlanDiagnostic(change.path, check, "error", str(error)[:1000], getattr(error, "lineno", None))

    def _entry(self, index: int, change: MaterializedFileChange, root: PlanDirectory, directory: PlanDirectory) -> PlanEntry:
        # reject aliases for writes and capture both immutable versions before staging a replacement
        if change.path != change.canonical_path:
            raise ChangeInputError("Recoverable edits require canonical paths without symlink aliases")
        with root.parent(change.path) as parent:
            name = Path(change.path).name
            before = parent.state(name)
            if (None if before is None else before.sha256) != change.expected_sha256:
                raise ChangeConflict(f"Source changed while preparing: {change.path}")
            encoding = self._project.project_config.encoding
            if change.old_content is not None:
                directory.write_new(f"old-{index}", change.old_content.encode(encoding))
            if change.new_content is not None:
                content = change.new_content.encode(encoding)
                directory.write_new(f"new-{index}", content)
                if before is None:
                    directory.write_new(f"slot-{index}", content)
                else:
                    with parent.file(name) as original:
                        if FileState.read(original) != before:
                            raise ChangeConflict(f"Source changed before metadata capture: {change.path}")
                        directory.write_new(f"slot-{index}", content, metadata_fd=original)
            staged = directory.state(f"slot-{index}")
            if before != parent.state(name):
                raise ChangeConflict(f"Source changed during staging: {change.path}")
            ranges = change.ranges
            if len(ranges) > 128:
                ranges = (ChangedRange(0, len((change.old_content or "").splitlines()), 0, len((change.new_content or "").splitlines())),)
            return PlanEntry(change.path, change.kind, before, change.proposed_sha256, staged, *parent.identity, ranges)

    def _report(self, plan_id: str, journal: PlanJournal, root: PlanDirectory, manifest: PlanManifest, *, action: str) -> PlanResult:
        execution = PlanExecution(root, journal, manifest, self._observer)
        files = execution.inspect() if action == "inspect" else execution.execute("rollback" if action == "rollback" else "apply")
        statuses = {entry.status for entry in files}
        if statuses == {"applied"}:
            status = "applied"
        elif statuses <= {"pending", "rolled_back"} and "rolled_back" in statuses:
            status = "rolled_back"
        elif statuses == {"pending"}:
            status = "prepared"
        elif statuses == {"conflict"}:
            status = "conflict"
        elif statuses == {"failed"}:
            status = "failed"
        else:
            status = "partial"
        checks = ("project_identity", "manifest_digest", "retained_snapshot_hashes", "source_and_slot_observation")
        return PlanResult(
            plan_id,
            status,
            files,
            tuple(
                PlannedFile(item.path, item.kind, None if item.before is None else item.before.sha256, item.proposed_sha256, item.ranges)
                for item in manifest.entries
            ),
            ExecutionPolicy(),
            manifest.diagnostics,
            f".selene/change-plans/{manifest.request_digest}",
            checks,
            self._LIMITATIONS,
        )

    def prepare(
        self,
        request_id: str,
        *,
        diff: str = "",
        changes: tuple[ProposedFileChange, ...] = (),
        allow_syntax_errors: bool = False,
    ) -> PlanResult:
        """Persist a bounded unapplied proposal; repeated IDs return the same content-bound plan."""
        AtomicRename()
        request_digest = PlanJournal.request_digest(request_id)
        input_digest = PlanJournal.digest(
            PlanJournal.encode(
                {"diff": diff, "changes": [asdict(change) for change in changes], "allow_syntax_errors": allow_syntax_errors}
            )
        )
        with PlanDirectory.root(self._root) as root, PlanJournal.locked(root) as storage:
            self._index.scope.validate_root()
            try:
                with storage.child(request_digest, private=True) as directory:
                    journal = PlanJournal(directory)
                    manifest = journal.load_manifest()
                    if manifest.input_digest != input_digest:
                        raise ChangeConflict("request_id was already used with different proposed contents")
                    plan_id = request_digest + "." + PlanJournal.digest(directory.read("manifest.json"))
                    journal.validate_project(manifest, root, self._root)
                    self._validate_snapshots(journal, manifest)
                    return self._report(plan_id, journal, root, manifest, action="inspect")
            except FileNotFoundError:
                pass
            if len(os.listdir(storage.fd)) >= 66:
                raise ChangeInputError(
                    "Recovery storage contains 64 plans or interrupted preparations; review and remove completed plans before adding more"
                )
            self._project.ls_sync_file_system_changes()
            sources = ContextSources(self._index, self._index.refresh(), self._project.project_config.encoding)
            resolver = ChangeResolver(self._project, sources)
            resolved = resolver.resolve(diff=diff, changes=changes)
            diagnostics = tuple(self._diagnostic(change) for change in resolved)
            nonce = uuid.uuid4().hex
            temporary = f"preparing-{nonce}"
            with storage.child(temporary, create=True, private=True) as directory:
                entries = tuple(self._entry(index, change, root, directory) for index, change in enumerate(resolved))
                for entry in entries:
                    self._validate_path(entry)
                resolver.validate(resolved)
                manifest = PlanManifest(
                    1,
                    nonce,
                    request_digest,
                    input_digest,
                    str(self._root),
                    *root.identity,
                    self._project.project_config.encoding,
                    allow_syntax_errors,
                    entries,
                    diagnostics,
                )
                journal = PlanJournal(directory)
                plan_id = journal.save_manifest(manifest)
                self._validate_snapshots(journal, manifest)
                CancellationToken.check_current()
                AtomicRename().move(storage.fd, temporary, storage.fd, request_digest, exchange=False)
                os.fsync(storage.fd)
                return self._report(plan_id, journal, root, manifest, action="inspect")

    @staticmethod
    def _validate_snapshots(journal: PlanJournal, manifest: PlanManifest) -> None:
        for index, entry in enumerate(manifest.entries):
            journal.body(index, "old", None if entry.before is None else entry.before.sha256)
            journal.body(index, "new", entry.proposed_sha256)

    def run(self, plan_id: str, *, action: Literal["apply", "inspect", "rollback"] = "apply") -> PlanResult:
        """Reconcile persisted operations before applying, inspecting or rolling back a plan."""
        if action not in {"apply", "inspect", "rollback"}:
            raise ChangeInputError("Choose apply, inspect or rollback")
        AtomicRename()
        directory_name = PlanJournal.directory_name(plan_id)
        with PlanDirectory.root(self._root) as root, PlanJournal.locked(root) as storage:
            with storage.child(directory_name, private=True) as directory:
                journal = PlanJournal(directory)
                manifest = journal.load_manifest(plan_id)
                journal.validate_project(manifest, root, self._root)
                self._validate_snapshots(journal, manifest)
                for entry in manifest.entries:
                    self._validate_path(entry)
                if action != "inspect":
                    self._project.ls_sync_file_system_changes()
                try:
                    return self._report(plan_id, journal, root, manifest, action=action)
                finally:
                    if action != "inspect":
                        for entry in manifest.entries:
                            self._project.record_local_write(entry.path)
