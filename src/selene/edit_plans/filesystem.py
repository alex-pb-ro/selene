"""Descriptor-relative file exchange and durable local recovery storage."""

import ctypes
import os
import stat
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from selene.changes.model import ChangeConflict, ChangeInputError
from selene.util.file_snapshot import FileSnapshotReader


@dataclass(frozen=True)
class FileState:
    """Content and inode identity observed through an opened regular file."""

    sha256: str
    device: int
    inode: int
    mode: int
    uid: int
    gid: int

    @classmethod
    def read(cls, descriptor: int) -> "FileState":
        snapshot = FileSnapshotReader.read_descriptor(descriptor, max_bytes=2 * 1024 * 1024)
        metadata = os.fstat(descriptor)
        if metadata.st_nlink != 1:
            raise ChangeInputError("Recoverable edits require files without hard-link aliases")
        return cls(snapshot.sha256, metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_uid, metadata.st_gid)

    def same_inode(self, other: "FileState | None") -> bool:
        return other is not None and (self.device, self.inode) == (other.device, other.inode)


class AtomicRename:
    """Exchange existing names or move to an absent name without destroying the destination.

    Supported implementations are Darwin ``renameatx_np`` and Linux ``renameat2``.
    Unsupported kernels/filesystems fail rather than falling back to overwriting rename.
    """

    def __init__(self) -> None:
        self._libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            self._rename = self._libc.renameatx_np
            self._exchange, self._exclusive = 2, 4
        elif sys.platform == "linux" and hasattr(self._libc, "renameat2"):
            self._rename = self._libc.renameat2
            self._exchange, self._exclusive = 2, 1
        else:
            raise ChangeInputError("Recoverable edits require Darwin or Linux with atomic exchange support")
        self._rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        self._rename.restype = ctypes.c_int

    def move(self, source_fd: int, source: str, target_fd: int, target: str, *, exchange: bool) -> None:
        flags = self._exchange if exchange else self._exclusive
        if self._rename(source_fd, os.fsencode(source), target_fd, os.fsencode(target), flags) != 0:
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number))

    def copy_metadata(self, source: int, target: int) -> None:
        """Preserve owner, group, permissions, ACLs and extended attributes on staged replacements."""
        metadata = os.fstat(source)
        if metadata.st_uid != os.geteuid() or metadata.st_mode & (stat.S_ISUID | stat.S_ISGID):
            raise ChangeInputError("Recoverable edits require owned files without set-user/group-ID bits")
        if sys.platform == "darwin":
            copy = self._libc.fcopyfile
            copy.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
            copy.restype = ctypes.c_int
            if copy(source, target, None, 7) != 0:  # COPYFILE_METADATA: ACL | STAT | XATTR
                number = ctypes.get_errno()
                raise OSError(number, os.strerror(number))
        else:
            os.fchown(target, metadata.st_uid, metadata.st_gid)
            os.fchmod(target, stat.S_IMODE(metadata.st_mode))
            for name in os.listxattr(source):
                os.setxattr(target, name, os.getxattr(source, name))


class PlanDirectory:
    """An owned directory descriptor with bounded, no-follow file access."""

    _DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

    def __init__(self, descriptor: int):
        self.fd = descriptor
        value = os.fstat(descriptor)
        self.identity: tuple[int, int] = (value.st_dev, value.st_ino)

    @staticmethod
    def _name(name: str) -> str:
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            raise ChangeInputError("Expected a single safe path component")
        return name

    @classmethod
    @contextmanager
    def root(cls, path: Path) -> Iterator["PlanDirectory"]:
        directory = cls(os.open(path, cls._DIRECTORY_FLAGS))
        try:
            yield directory
        finally:
            os.close(directory.fd)

    @contextmanager
    def child(self, name: str, *, create: bool = False, private: bool = False) -> Iterator["PlanDirectory"]:
        name = self._name(name)
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=self.fd)
                os.fsync(self.fd)
            except FileExistsError:
                pass
        child = PlanDirectory(os.open(name, self._DIRECTORY_FLAGS, dir_fd=self.fd))
        try:
            value = os.fstat(child.fd)
            if private and (value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) & 0o077):
                raise ChangeInputError("Recovery directories must be owned by the current user and private (0700)")
            if value.st_dev != self.identity[0]:
                raise ChangeInputError("Recovery operations must stay on the project filesystem")
            yield child
        finally:
            os.close(child.fd)

    @contextmanager
    def parent(self, path: str) -> Iterator["PlanDirectory"]:
        parts = Path(path).parts
        if not parts or Path(path).is_absolute() or ".." in parts:
            raise ChangeInputError("Changed paths must be project-relative without parent traversal")
        if len(parts) == 1:
            yield self
        else:
            with self.child(parts[0]) as directory:
                with directory.parent(Path(*parts[1:]).as_posix()) as parent:
                    yield parent

    @contextmanager
    def file(self, name: str) -> Iterator[int]:
        descriptor = os.open(self._name(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    def state(self, name: str) -> FileState | None:
        try:
            with self.file(name) as descriptor:
                return FileState.read(descriptor)
        except FileNotFoundError:
            return None

    def read(self, name: str, *, max_bytes: int = 2 * 1024 * 1024) -> bytes:
        with self.file(name) as descriptor:
            return FileSnapshotReader.read_descriptor(descriptor, max_bytes=max_bytes).content

    def write_new(self, name: str, content: bytes, *, metadata_fd: int | None = None) -> None:
        # publish complete, synced bytes without exposing a partially written journal record
        name = self._name(name)
        temporary = "writing-" + uuid.uuid4().hex
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
            if metadata_fd is not None:
                AtomicRename().copy_metadata(metadata_fd, descriptor)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            AtomicRename().move(self.fd, temporary, self.fd, name, exchange=False)
        except FileExistsError:
            # discard only this call's unpublished scratch file; preserve every published version
            os.unlink(temporary, dir_fd=self.fd)
            raise
        os.fsync(self.fd)

    def verify_parent(self, root: "PlanDirectory", path: str) -> None:
        with root.parent(path) as current:
            if current.identity != self.identity:
                raise ChangeConflict(f"Parent directory changed: {path}")
