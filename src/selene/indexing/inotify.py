"""Linux inotify adapter with explicit queue-loss and directory-watch recovery."""

import ctypes
import os
import struct
import time
from pathlib import Path

from selene.indexing.journal import ChangeBatch, ChangeJournal, WatchUnavailable
from selene.indexing.scope import IndexInclusionPolicy
from selene.util.cancellation import CancellationToken


class InotifyJournal(ChangeJournal):
    _MODIFY = 0x00000002
    _ATTRIB = 0x00000004
    _CLOSE_WRITE = 0x00000008
    _MOVED_FROM = 0x00000040
    _MOVED_TO = 0x00000080
    _CREATE = 0x00000100
    _DELETE = 0x00000200
    _DELETE_SELF = 0x00000400
    _MOVE_SELF = 0x00000800
    _UNMOUNT = 0x00002000
    _OVERFLOW = 0x00004000
    _IGNORED = 0x00008000
    _ONLY_DIR = 0x01000000
    _DONT_FOLLOW = 0x02000000
    _IS_DIR = 0x40000000
    _HEADER = struct.Struct("iIII")

    def __init__(self, root: Path, policy: IndexInclusionPolicy, pending_limit: int = 10_000):
        super().__init__(root, pending_limit)
        self._policy = policy
        self._libc = ctypes.CDLL(None, use_errno=True)
        self._libc.inotify_init1.argtypes = [ctypes.c_int]
        self._libc.inotify_init1.restype = ctypes.c_int
        self._libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._libc.inotify_add_watch.restype = ctypes.c_int
        self._descriptor = -1
        self._directories: dict[int, Path] = {}
        self.rebuild()

    def _add(self, descriptor: int, directory: Path, watches: dict[int, Path]) -> None:
        mask = (
            self._MODIFY
            | self._ATTRIB
            | self._CLOSE_WRITE
            | self._MOVED_FROM
            | self._MOVED_TO
            | self._CREATE
            | self._DELETE
            | self._DELETE_SELF
            | self._MOVE_SELF
            | self._ONLY_DIR
            | self._DONT_FOLLOW
        )
        watch = self._libc.inotify_add_watch(descriptor, os.fsencode(directory), mask)
        if watch < 0:
            error = ctypes.get_errno()
            raise OSError(error, "Cannot establish a directory watch", str(directory))
        watches[watch] = directory

    def rebuild(self) -> None:
        descriptor = self._libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if descriptor < 0:
            raise WatchUnavailable("Cannot initialize inotify")
        watches: dict[int, Path] = {}

        def on_error(error: OSError) -> None:
            raise error

        try:
            # start at the root before enumeration so newly created subtrees remain observable
            self._add(descriptor, self.root, watches)
            for root, directories, _ in os.walk(self.root, followlinks=False, onerror=on_error):
                CancellationToken.check_current()
                path = Path(root)
                relative = path.relative_to(self.root).as_posix()
                if path != self.root:
                    try:
                        self._add(descriptor, path, watches)
                    except FileNotFoundError:
                        directories.clear()
                        continue
                directories[:] = [
                    name
                    for name in directories
                    if not (path / name).is_symlink()
                    and (
                        self._policy.includes((Path(relative) / name).as_posix(), directory=True)
                        or (path == self.root and name == ".git")
                        or (relative == ".git" and name == "info")
                    )
                ]
        except BaseException:
            os.close(descriptor)
            raise
        previous = self._descriptor
        self._descriptor, self._directories = descriptor, watches
        if previous >= 0:
            os.close(previous)

    def read(self) -> ChangeBatch:
        if self._descriptor < 0:
            raise WatchUnavailable("The inotify journal is closed")
        deadline = time.monotonic() + 0.25
        while True:
            CancellationToken.check_current()
            try:
                data = os.read(self._descriptor, 256 * 1024)
            except BlockingIOError:
                return self._snapshot()
            if not data:
                raise WatchUnavailable("The inotify event stream ended")
            offset = 0
            while offset < len(data):
                if offset + self._HEADER.size > len(data):
                    raise WatchUnavailable("Incomplete inotify event header")
                watch, mask, _, length = self._HEADER.unpack_from(data, offset)
                offset += self._HEADER.size
                if offset + length > len(data):
                    raise WatchUnavailable("Incomplete inotify event path")
                name = os.fsdecode(data[offset : offset + length].split(b"\0", 1)[0])
                offset += length
                if mask & self._OVERFLOW:
                    self.invalidate("kernel_event_overflow")
                    continue
                directory = self._directories.get(watch)
                if directory is None:
                    self.invalidate("unknown_directory_watch")
                    continue
                relative = (directory / name).relative_to(self.root).as_posix()
                self.record_local_write(relative)
                if mask & (self._DELETE_SELF | self._MOVE_SELF | self._UNMOUNT | self._IGNORED):
                    self.invalidate("directory_watch_changed")
                elif mask & self._IS_DIR and mask & (self._CREATE | self._DELETE | self._MOVED_FROM | self._MOVED_TO):
                    self.invalidate("directory_structure_changed")
            if time.monotonic() > deadline:
                self.invalidate("event_drain_budget_exceeded")
                return self._snapshot()

    def close(self) -> None:
        if self._descriptor >= 0:
            os.close(self._descriptor)
            self._descriptor = -1
