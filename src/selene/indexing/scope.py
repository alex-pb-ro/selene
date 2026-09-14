"""Project-root ownership for local indexing, retrieval and evidence."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from selene.util.cancellation import CancellationToken
from selene.util.file_snapshot import FileSnapshot, FileSnapshotConflict, FileSnapshotReader, FileStamp


class SourceScopeError(ValueError):
    """A requested source path is outside the registered project scope."""


class SourceRootReplaced(RuntimeError):
    """The registered project root no longer identifies the original directory."""


class IndexInclusionPolicy(Protocol):
    """Decide which project paths belong to a local index."""

    def includes(self, relative_path: str, *, directory: bool) -> bool: ...

    def is_source(self, relative_path: str) -> bool: ...

    def refresh(self) -> None: ...

    def signature(self) -> str: ...


@dataclass(frozen=True)
class ScopeIssue:
    path: str
    reason: str


@dataclass(frozen=True)
class SourceTree:
    files: tuple[str, ...]
    directories: tuple[str, ...]
    issues: tuple[ScopeIssue, ...]
    has_aliases: bool


class ProjectSourceScope:
    """Read project files through a fixed root identity and validated relative paths.

    In-root symlinks are supported, while escaping links and directory cycles are excluded.
    POSIX reads traverse the resolved components using directory descriptors and no-follow
    opens. The final path identity is checked again before returning captured bytes.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve(strict=True)
        root_stat = self.root.stat()
        if not stat.S_ISDIR(root_stat.st_mode):
            raise SourceScopeError("The project root must be a directory")
        self._identity = (root_stat.st_dev, root_stat.st_ino)

    @staticmethod
    def normalize(relative_path: str) -> str:
        path = Path(relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise SourceScopeError("Source paths must be relative to the project without parent traversal")
        return "" if str(path) == "." else path.as_posix()

    def resolve(self, relative_path: str) -> Path:
        relative_path = self.normalize(relative_path)
        resolved = (self.root / relative_path).resolve(strict=True)
        if not resolved.is_relative_to(self.root):
            raise SourceScopeError(f"Source path escapes the project: {relative_path}")
        return resolved

    def validate_root(self) -> None:
        root_stat = self.root.stat()
        if (root_stat.st_dev, root_stat.st_ino) != self._identity:
            raise SourceRootReplaced("The registered project root was replaced; reactivate it before indexing")

    @contextmanager
    def _open(self, relative_path: str, *, directory: bool = False) -> Iterator[int]:
        CancellationToken.check_current()
        self.validate_root()
        resolved = self.resolve(relative_path)
        if os.open not in os.supports_dir_fd:
            # validate identities around portable reads; deployments own OS-level confinement
            descriptor = None if directory else os.open(resolved, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            try:
                before = FileStamp.read(resolved) if descriptor is None else FileStamp.from_stat(os.fstat(descriptor))
                if before != FileStamp.read(self.resolve(relative_path)):
                    raise FileSnapshotConflict("Source path changed while opening it")
                yield -1 if descriptor is None else descriptor
                self.validate_root()
                if self.resolve(relative_path) != resolved or before != FileStamp.read(resolved):
                    raise FileSnapshotConflict("Source path changed while it was being used")
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            return
        parts = resolved.relative_to(self.root).parts
        root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(self.root, root_flags)
        descriptor = root_fd
        try:
            root_stat = os.fstat(root_fd)
            if (root_stat.st_dev, root_stat.st_ino) != self._identity:
                raise SourceRootReplaced("The registered project root was replaced; reactivate it before indexing")
            if os.open in os.supports_dir_fd:
                for position, part in enumerate(parts):
                    flags = (
                        root_flags
                        if directory or position < len(parts) - 1
                        else (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
                    )
                    next_fd = os.open(part, flags, dir_fd=descriptor)
                    if descriptor != root_fd:
                        os.close(descriptor)
                    descriptor = next_fd
            opened = os.fstat(descriptor)
            current = self.resolve(relative_path).stat()
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise FileSnapshotConflict("Source path changed while opening it")
            yield descriptor
            self.validate_root()
            if self.resolve(relative_path) != resolved or FileStamp.from_stat(os.fstat(descriptor)) != FileStamp.read(resolved):
                raise FileSnapshotConflict("Source path changed while it was being used")
        finally:
            if descriptor != root_fd:
                os.close(descriptor)
            os.close(root_fd)

    def read(self, relative_path: str, *, max_bytes: int | None = None) -> FileSnapshot:
        with self._open(relative_path) as descriptor:
            return FileSnapshotReader.read_descriptor(descriptor, max_bytes=max_bytes)

    def fingerprint(self, relative_path: str) -> str:
        with self._open(relative_path) as descriptor:
            return FileSnapshotReader.fingerprint_descriptor(descriptor)

    def stamp(self, relative_path: str) -> FileStamp:
        with self._open(relative_path) as descriptor:
            return FileStamp.from_stat(os.fstat(descriptor))

    def scan(self, policy: IndexInclusionPolicy, relative_path: str = "") -> SourceTree:
        self.validate_root()
        files: list[str] = []
        directories: set[str] = set()
        issues: list[ScopeIssue] = []
        has_aliases = False

        def visit(path: str, ancestors: frozenset[tuple[int, int]]) -> None:
            nonlocal has_aliases
            CancellationToken.check_current()
            original = self.root / path
            try:
                original_stat = original.lstat()
                if not policy.includes(path, directory=stat.S_ISDIR(original_stat.st_mode)):
                    return
                resolved = self.resolve(path)
                current_stat = resolved.stat()
                directory = stat.S_ISDIR(current_stat.st_mode)
                if not policy.includes(path, directory=directory):
                    return
                if not policy.includes(resolved.relative_to(self.root).as_posix(), directory=directory):
                    return
                if stat.S_ISLNK(original_stat.st_mode):
                    has_aliases = True
                if directory:
                    identity = (current_stat.st_dev, current_stat.st_ino)
                    if identity in ancestors:
                        issues.append(ScopeIssue(path, "directory_symlink_cycle"))
                        return
                    directories.add(resolved.relative_to(self.root).as_posix())
                    with self._open(path, directory=True) as descriptor:
                        scan_path = descriptor if os.scandir in os.supports_fd else resolved
                        with os.scandir(scan_path) as entries:
                            names = sorted(entry.name for entry in entries)
                    for name in names:
                        visit((Path(path) / name).as_posix(), ancestors | {identity})
                elif stat.S_ISREG(current_stat.st_mode):
                    files.append(path)
                else:
                    issues.append(ScopeIssue(path, "non_regular_file"))
            except FileNotFoundError:
                return
            except SourceScopeError:
                if policy.includes(path, directory=True):
                    issues.append(ScopeIssue(path, "outside_project"))

        visit(self.normalize(relative_path), frozenset())
        self.validate_root()
        return SourceTree(tuple(files), tuple(sorted(directories)), tuple(issues), has_aliases)
