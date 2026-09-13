"""Acknowledged filesystem changes: cancellation cannot discard pending observations."""

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class WatchUnavailable(RuntimeError):
    """A native watcher cannot currently establish a synchronization boundary."""


@dataclass(frozen=True)
class ChangeBatch:
    cursor: int
    paths: frozenset[str]
    reconcile: bool
    reasons: tuple[str, ...]


class ChangeJournal(ABC):
    """Retain events until the index has committed a corresponding observation."""

    def __init__(self, root: Path, pending_limit: int = 10_000):
        if pending_limit < 1:
            raise ValueError("The pending event limit must be positive")
        self.root = root
        self._pending_limit = pending_limit
        self._lock = threading.Lock()
        self._cursor = 0
        self._paths: dict[str, int] = {}
        self._reasons: dict[str, int] = {}

    def record_local_write(self, relative_path: str) -> None:
        """Record an explicit project edit, also used by native event adapters."""
        with self._lock:
            self._cursor += 1
            if len(self._paths) >= self._pending_limit and relative_path not in self._paths:
                self._paths.clear()
                self._reasons["event_buffer_overflow"] = self._cursor
            self._paths[relative_path] = self._cursor

    def invalidate(self, reason: str) -> None:
        """Require reconciliation after event loss or a configuration change."""
        with self._lock:
            self._cursor += 1
            self._reasons[reason] = self._cursor

    def acknowledge(self, cursor: int) -> None:
        """Discard only changes covered by a committed observation, retaining newer same-path events."""
        with self._lock:
            self._paths = {path: sequence for path, sequence in self._paths.items() if sequence > cursor}
            self._reasons = {reason: sequence for reason, sequence in self._reasons.items() if sequence > cursor}

    def _snapshot(self) -> ChangeBatch:
        with self._lock:
            return ChangeBatch(self._cursor, frozenset(self._paths), bool(self._reasons), tuple(sorted(self._reasons)))

    @abstractmethod
    def read(self) -> ChangeBatch:
        """Drain native events through a synchronization boundary without acknowledging them."""

    @abstractmethod
    def rebuild(self) -> None:
        """Restore native coverage before a complete source reconciliation."""

    @abstractmethod
    def close(self) -> None:
        """Release native resources."""
