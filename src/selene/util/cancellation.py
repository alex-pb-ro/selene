"""Cooperative cancellation shared by request, task, file and subprocess boundaries."""

from collections.abc import Callable, Iterator
from concurrent.futures import CancelledError
from contextlib import contextmanager
from contextvars import ContextVar
from math import isfinite
from threading import Event, Lock
from time import monotonic
from weakref import WeakSet


class CancellationToken:
    """A cancellation request and deadline, optionally nested under another operation.

    Cancellation prevents work at the next checkpoint. It cannot interrupt arbitrary Python
    code or undo an already started write; the executor retains ownership until that code exits.
    """

    _current: ContextVar["CancellationToken | None"] = ContextVar("operation_cancellation", default=None)

    def __init__(self, timeout: float | None = None, on_cancel: Callable[[], None] | None = None) -> None:
        if timeout is not None and (not isfinite(timeout) or timeout < 0):
            raise ValueError("Operation timeout must be finite and non-negative")
        self._parent = self._current.get()
        self._deadline = None if timeout is None else monotonic() + timeout
        self._cancelled = Event()
        self._lock = Lock()
        self._children: WeakSet[CancellationToken] = WeakSet()
        self._on_cancel = on_cancel
        if self._parent is not None:
            self._parent._register_child(self)

    def _register_child(self, child: "CancellationToken") -> None:
        with self._lock:
            self._children.add(child)
        if self._cancelled.is_set():
            child.cancel()

    def cancel(self) -> None:
        """Request cancellation without claiming that execution has stopped."""
        with self._lock:
            if self._cancelled.is_set():
                return
            self._cancelled.set()
            children = list(self._children)
        for child in children:
            child.cancel()
        if self._on_cancel is not None:
            self._on_cancel()

    def remaining(self) -> float | None:
        """Return the time remaining until the earliest enclosing deadline."""
        remaining = None if self._deadline is None else max(0.0, self._deadline - monotonic())
        parent_remaining = None if self._parent is None else self._parent.remaining()
        if parent_remaining is None:
            return remaining
        return parent_remaining if remaining is None else min(remaining, parent_remaining)

    def check(self) -> None:
        """Raise when cancellation was requested or an enclosing deadline expired."""
        if self._parent is not None:
            self._parent.check()
        if self._cancelled.is_set():
            raise CancelledError("Operation cancellation requested")
        if self._deadline is not None and monotonic() >= self._deadline:
            raise TimeoutError("Operation deadline exceeded")

    @contextmanager
    def bind(self) -> Iterator[None]:
        """Make this token available to checkpoints in the current execution context."""
        previous = self._current.set(self)
        try:
            yield
        finally:
            self._current.reset(previous)

    @classmethod
    def check_current(cls) -> None:
        """Check the active operation, if any."""
        current = cls._current.get()
        if current is not None:
            current.check()
