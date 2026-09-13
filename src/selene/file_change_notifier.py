"""Ordered source observations and retryable delivery to language servers."""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from selene.util.cancellation import CancellationToken
from selene.util.file_snapshot import FileSnapshotReader
from solidlsp import SolidLanguageServer
from solidlsp.lsp_protocol_handler.lsp_types import DidChangeWatchedFilesParams, FileChangeType, FileEvent

if TYPE_CHECKING:
    from selene.ls_manager import LanguageServerManager
    from selene.project import Project


class LanguageServerFileChangeNotifier:
    """Compare source fingerprints and retain unacknowledged changes for each server.

    Delivery means that the local LSP transport accepted the notification, not that the
    language server has finished indexing. Server-specific indexing barriers still apply.
    """

    @dataclass
    class _ServerState:
        snapshot: dict[str, str]
        uncertain_paths: set[str] = field(default_factory=set)

    def __init__(self, project: "Project", language_server_manager: "LanguageServerManager", initial_poll: bool = True) -> None:
        self._project = project
        self._language_server_manager = language_server_manager
        self._last_observed: dict[str, str] | None = None
        self._server_states: dict[SolidLanguageServer, LanguageServerFileChangeNotifier._ServerState] = {}
        self._lock = threading.Lock()
        if initial_poll:
            self.poll_and_notify()

    @staticmethod
    def _events(previous: dict[str, str], current: dict[str, str], uncertain: set[str]) -> dict[str, FileChangeType]:
        events = {}
        for path, fingerprint in current.items():
            if path not in previous:
                events[path] = FileChangeType.Created
            elif fingerprint != previous[path] or path in uncertain:
                events[path] = FileChangeType.Changed
        for path in previous.keys() | uncertain:
            if path not in current:
                events[path] = FileChangeType.Deleted
        return events

    def _observe(self) -> dict[str, str]:
        snapshot = {}
        for relative_path in self._project.gather_source_files():
            CancellationToken.check_current()
            try:
                snapshot[relative_path] = FileSnapshotReader.fingerprint(Path(self._project.project_root, relative_path))
            except FileNotFoundError:
                # discovery may race with deletion; other read errors must not look like deletions
                continue
        return snapshot

    def poll_and_notify(self) -> int:
        """Observe source files in order and deliver changes to every language server.

        The first observation establishes a baseline. Subsequent observations hash the files
        tracked by the project, so same-size edits with restored timestamps remain visible.
        Notification failures are raised and retained for retry, including ambiguous deliveries
        followed by a source change back to the previous contents.

        :return: the number of distinct paths changed or requiring notification retry
        """
        with self._lock:
            return self._poll_and_notify()

    def _poll_and_notify(self) -> int:
        # serialize observation and delivery so a slow scan cannot replace a newer baseline
        current = self._observe()
        servers = list(self._language_server_manager.iter_language_servers())
        previous = self._last_observed
        self._last_observed = current
        self._server_states = {server: state for server, state in self._server_states.items() if server in servers}
        if previous is None:
            self._server_states = {server: self._ServerState(current) for server in servers}
            return 0

        changed_paths = set(self._events(previous, current, set()))
        failures = []
        for server in servers:
            CancellationToken.check_current()
            state = self._server_states.setdefault(server, self._ServerState(previous))
            events = self._events(state.snapshot, current, state.uncertain_paths)
            changed_paths.update(events)
            if events:
                try:
                    self._notify(server, events, state.uncertain_paths)
                except Exception as error:
                    state.uncertain_paths.update(events)
                    failures.append(error)
                    continue
            state.snapshot = current
            state.uncertain_paths.clear()

        if failures:
            # preserve the exception type so terminated-server recovery remains available
            raise failures[0]
        return len(changed_paths)

    def _notify(self, server: SolidLanguageServer, events: dict[str, FileChangeType], uncertain: set[str]) -> None:
        changes: list[FileEvent] = [
            {"uri": Path(self._project.project_root, path).resolve().as_uri(), "type": change_type}
            for path, change_type in sorted(events.items())
        ]
        params: DidChangeWatchedFilesParams = {"changes": changes}
        server.server.notify.did_change_watched_files(params)

        # opening a new or uncertain file also triggers binding in backends such as Pyright
        for path, change_type in events.items():
            if change_type != FileChangeType.Created and not (path in uncertain and change_type != FileChangeType.Deleted):
                continue
            if server.is_ignored_path(path, ignore_unsupported_files=True):
                continue
            CancellationToken.check_current()
            with server.open_file(path):
                pass
