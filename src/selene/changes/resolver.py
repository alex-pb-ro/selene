"""Resolve source-preconditioned change inputs without modifying the project."""

import difflib
import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from selene.changes.model import ChangeConflict, ChangedRange, ChangeInputError, MaterializedFileChange, ProposedFileChange
from selene.changes.unified_diff import UnifiedDiff
from selene.context.sources import ContextSources
from selene.indexing.project_policy import ProjectIndexPolicy
from selene.util.cancellation import CancellationToken

if TYPE_CHECKING:
    from selene.project import Project


class ChangeResolver:
    """Materialize bounded text proposals against the active project's source versions."""

    def __init__(self, project: "Project", sources: ContextSources):
        self._project = project
        self._sources = sources
        self._policy = ProjectIndexPolicy(project)

    def _before(self, path: str) -> tuple[str | None, str | None, str]:
        scope = self._sources.index.scope
        scope.validate_root()
        path = scope.normalize(path)
        if not path or not self._policy.includes(path, directory=False):
            raise ChangeInputError("Changed files must be included project source paths")
        for parent in Path(path).parents:
            if not self._policy.includes(parent.as_posix(), directory=True):
                raise ChangeInputError("A changed file is below an excluded directory")
        entry = self._sources.observation.files.get(path)
        if entry is not None:
            document = self._sources.read(path)
            snapshot = scope.read(path, max_bytes=2 * 1024 * 1024)
            if snapshot.sha256 != document.sha256:
                raise ChangeConflict(f"Source changed while resolving the proposal: {path}")
            return snapshot.content.decode(self._project.project_config.encoding), document.sha256, document.canonical_path
        if os.path.lexists(scope.root / path):
            raise ChangeInputError("Existing changed files must be searchable in the project index")
        parent = (scope.root / path).parent.resolve(strict=False)
        if not parent.is_relative_to(scope.root):
            raise ChangeInputError("The proposed new file would escape the project")
        canonical = (parent / Path(path).name).relative_to(scope.root).as_posix()
        if not self._policy.includes(canonical, directory=False):
            raise ChangeInputError("The proposed canonical path is excluded")
        return None, None, canonical

    def resolve(self, *, diff: str = "", changes: tuple[ProposedFileChange, ...] = ()) -> tuple[MaterializedFileChange, ...]:
        if bool(diff) == bool(changes):
            raise ChangeInputError("Provide exactly one of a unified diff or structured file changes")
        if diff:
            proposals = []
            for patch in UnifiedDiff.parse(diff):
                before, sha256, _ = self._before(patch.path)
                proposals.append(ProposedFileChange(patch.path, sha256, patch.apply(before)))
            changes = tuple(proposals)
        if not 1 <= len(changes) <= 16:
            raise ChangeInputError("Provide between one and sixteen changed files")
        results = []
        seen = set()
        total_bytes = 0
        for change in changes:
            CancellationToken.check_current()
            path = self._sources.index.scope.normalize(change.path)
            before, sha256, canonical = self._before(path)
            if canonical in seen:
                raise ChangeInputError("A change set must not edit the same canonical file more than once")
            seen.add(canonical)
            if sha256 != change.expected_sha256:
                raise ChangeConflict(f"Source precondition does not match: {path}")
            if before is None and change.new_content is None:
                raise ChangeInputError("A missing file cannot be deleted")
            encoded = None if change.new_content is None else change.new_content.encode(self._project.project_config.encoding)
            size = len(encoded or b"")
            total_bytes += size
            if size > 2 * 1024 * 1024 or total_bytes > 8 * 1024 * 1024:
                raise ChangeInputError("Proposed content exceeds the 2 MiB/file or 8 MiB/change-set allowance")
            if encoded is not None and b"\x00" in encoded:
                raise ChangeInputError("Only text changes are supported")
            if before == change.new_content:
                continue
            old_lines = [] if before is None else before.splitlines()
            new_lines = [] if change.new_content is None else change.new_content.splitlines()
            matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=True)
            ranges = tuple(ChangedRange(a, b, c, d) for operation, a, b, c, d in matcher.get_opcodes() if operation != "equal")
            CancellationToken.check_current()
            if not ranges:
                ranges = (ChangedRange(0, len(old_lines), 0, len(new_lines)),)
            results.append(
                MaterializedFileChange(
                    path,
                    canonical,
                    "create" if before is None else "delete" if encoded is None else "modify",
                    sha256,
                    None if encoded is None else hashlib.sha256(encoded).hexdigest(),
                    before,
                    change.new_content,
                    ranges,
                )
            )
        if not results:
            raise ChangeInputError("The proposal contains no changes")
        self._sources.validate()
        return tuple(results)

    def validate(self, changes: tuple[MaterializedFileChange, ...]) -> None:
        """Recheck every source/existence precondition before publishing an analysis."""
        self._sources.validate()
        for change in changes:
            before, sha256, canonical = self._before(change.path)
            if sha256 != change.expected_sha256 or canonical != change.canonical_path or before != change.old_content:
                raise ChangeConflict(f"Source changed during proposal analysis: {change.path}")
