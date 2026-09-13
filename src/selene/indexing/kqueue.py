"""Darwin vnode watches with immediate kernel observations and bounded resources."""

import os
import select
import time
from pathlib import Path

from selene.indexing.journal import ChangeBatch, ChangeJournal, WatchUnavailable
from selene.indexing.scope import IndexInclusionPolicy
from selene.util.cancellation import CancellationToken


class KqueueJournal(ChangeJournal):
    """Watch each included inode; resource exhaustion makes coverage unavailable.

    Directory changes require a new watch set and content reconciliation. Existing-file
    writes only invalidate that file. No process-wide descriptor limits are changed.
    """

    def __init__(self, root: Path, policy: IndexInclusionPolicy, pending_limit: int = 10_000):
        super().__init__(root, pending_limit)
        self._policy = policy
        self._queue: select.kqueue | None = None
        self._watches: dict[int, tuple[str, bool]] = {}
        self.rebuild()

    def _add(self, queue: select.kqueue, path: Path, directory: bool, watches: dict[int, tuple[str, bool]]) -> None:
        descriptor = os.open(path, os.O_EVTONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            flags = (
                select.KQ_NOTE_WRITE
                | select.KQ_NOTE_EXTEND
                | select.KQ_NOTE_ATTRIB
                | select.KQ_NOTE_LINK
                | select.KQ_NOTE_RENAME
                | select.KQ_NOTE_DELETE
                | select.KQ_NOTE_REVOKE
            )
            queue.control(
                [select.kevent(descriptor, filter=select.KQ_FILTER_VNODE, flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR, fflags=flags)], 0, 0
            )
            watches[descriptor] = (path.relative_to(self.root).as_posix(), directory)
        except BaseException:
            os.close(descriptor)
            raise

    def rebuild(self) -> None:
        queue = select.kqueue()
        watches: dict[int, tuple[str, bool]] = {}

        def on_error(error: OSError) -> None:
            raise error

        try:
            # watch parents before enumerating children so concurrent additions force a rescan
            self._add(queue, self.root, True, watches)
            for root, directories, files in os.walk(self.root, followlinks=False, onerror=on_error):
                CancellationToken.check_current()
                path = Path(root)
                relative = path.relative_to(self.root).as_posix()
                if path != self.root:
                    try:
                        self._add(queue, path, True, watches)
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
                for name in files:
                    file = path / name
                    if file.is_symlink():
                        continue
                    relative_file = file.relative_to(self.root).as_posix()
                    if (
                        file.name != ".gitignore"
                        and not self._policy.includes(relative_file, directory=False)
                        and relative_file
                        not in {
                            ".git/HEAD",
                            ".git/index",
                            ".git/info/exclude",
                        }
                    ):
                        continue
                    try:
                        self._add(queue, file, False, watches)
                    except FileNotFoundError:
                        continue
        except BaseException:
            queue.close()
            for descriptor in watches:
                os.close(descriptor)
            raise
        self.close()
        self._queue, self._watches = queue, watches

    def read(self) -> ChangeBatch:
        if self._queue is None:
            raise WatchUnavailable("The vnode event journal is closed")
        deadline = time.monotonic() + 0.25
        while True:
            CancellationToken.check_current()
            events = self._queue.control(None, 1024, 0)
            if not events:
                return self._snapshot()
            for event in events:
                watched = self._watches.get(event.ident)
                if event.flags & (select.KQ_EV_ERROR | select.KQ_EV_EOF) or watched is None:
                    self.invalidate("vnode_watch_unavailable")
                    continue
                path, directory = watched
                self.record_local_write(path)
                if directory or event.fflags & (select.KQ_NOTE_RENAME | select.KQ_NOTE_DELETE | select.KQ_NOTE_REVOKE):
                    self.invalidate("directory_or_inode_changed")
            if time.monotonic() >= deadline:
                self.invalidate("event_drain_budget_exceeded")
                return self._snapshot()

    def close(self) -> None:
        if self._queue is not None:
            self._queue.close()
            self._queue = None
        for descriptor in self._watches:
            os.close(descriptor)
        self._watches.clear()
