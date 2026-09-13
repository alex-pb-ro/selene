"""Stable local file observations for freshness and mutation preconditions."""

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from selene.util.cancellation import CancellationToken


class FileSnapshotConflict(OSError):
    """The file changed during a read or conflicts with an unsaved buffer."""


@dataclass(frozen=True)
class FileStamp:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "FileStamp":
        return cls(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_mode)

    @classmethod
    def read(cls, path: str | Path) -> "FileStamp":
        return cls.from_stat(os.stat(path))


@dataclass(frozen=True)
class FileSnapshot:
    content: bytes
    sha256: str
    stamp: FileStamp


class FileSnapshotReader:
    """Read bytes and their fingerprint from the same stable file descriptor.

    Metadata is checked before and after reading, including the path's current identity.
    Unstable reads are retried a bounded number of times, then reported as conflicts.
    Callers remain responsible for deciding which paths may be accessed.
    """

    @dataclass(frozen=True)
    class _Capture:
        content: bytes | None
        sha256: str
        stamp: FileStamp

    @classmethod
    def read(cls, path: str | Path) -> FileSnapshot:
        capture = cls._capture(path, include_content=True)
        assert capture.content is not None
        return FileSnapshot(capture.content, capture.sha256, capture.stamp)

    @classmethod
    def fingerprint(cls, path: str | Path) -> str:
        """Hash a file without retaining its contents."""
        return cls._capture(path, include_content=False).sha256

    @classmethod
    def read_descriptor(cls, descriptor: int, *, max_bytes: int | None = None) -> FileSnapshot:
        """Capture a caller-owned, securely opened file descriptor without closing it."""
        capture = cls._capture_descriptor(descriptor, include_content=True, max_bytes=max_bytes)
        assert capture.content is not None
        return FileSnapshot(capture.content, capture.sha256, capture.stamp)

    @classmethod
    def fingerprint_descriptor(cls, descriptor: int) -> str:
        """Fingerprint a caller-owned descriptor without retaining content."""
        return cls._capture_descriptor(descriptor, include_content=False).sha256

    @classmethod
    def _capture_descriptor(cls, descriptor: int, *, include_content: bool, max_bytes: int | None = None) -> _Capture:
        before = FileStamp.from_stat(os.fstat(descriptor))
        if not stat.S_ISREG(before.mode):
            raise OSError("Expected a regular source file")
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        chunks = []
        size = 0
        while chunk := os.read(descriptor, 128 * 1024):
            CancellationToken.check_current()
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise FileSnapshotConflict("Source grew beyond the requested read limit")
            digest.update(chunk)
            if include_content:
                chunks.append(chunk)
        after = FileStamp.from_stat(os.fstat(descriptor))
        if before != after:
            raise FileSnapshotConflict("File changed while being read")
        return cls._Capture(b"".join(chunks) if include_content else None, digest.hexdigest(), after)

    @classmethod
    def _capture(cls, path: str | Path, *, include_content: bool) -> _Capture:
        for _ in range(3):
            CancellationToken.check_current()
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
            descriptor = os.open(path, flags)
            try:
                try:
                    capture = cls._capture_descriptor(descriptor, include_content=include_content)
                except FileSnapshotConflict:
                    continue
                if capture.stamp == FileStamp.read(path):
                    return capture
            finally:
                os.close(descriptor)
        raise FileSnapshotConflict(f"File changed repeatedly while being read: {path}")
