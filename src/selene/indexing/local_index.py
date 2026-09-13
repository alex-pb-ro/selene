"""An in-memory lexical index with acknowledged native invalidation and content versions."""

import math
import re
import sys
import threading
import time
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType

from selene.indexing.coverage import NativeWatchCoverage
from selene.indexing.journal import ChangeBatch, ChangeJournal, WatchUnavailable
from selene.indexing.scope import IndexInclusionPolicy, ProjectSourceScope, ScopeIssue, SourceScopeError
from selene.util.cancellation import CancellationToken
from selene.util.file_snapshot import FileSnapshotConflict


class IndexCatchingUp(RuntimeError):
    """Concurrent changes prevent the index from reaching a drained observation."""


@dataclass(frozen=True)
class IndexedFile:
    path: str
    canonical_path: str
    sha256: str
    source: bool
    terms: frozenset[str]
    text_status: str


@dataclass(frozen=True)
class IndexStatus:
    generation: int
    observed_at: float
    reconciled_at: float
    watcher: str
    ready: bool
    reconciliation_reasons: tuple[str, ...]
    files: int
    searchable_files: int
    issues: tuple[ScopeIssue, ...]


@dataclass(frozen=True)
class IndexObservation:
    status: IndexStatus
    files: Mapping[str, IndexedFile]
    source_fingerprints: Mapping[str, str]


@dataclass(frozen=True)
class IndexMatch:
    path: str
    sha256: str
    matched_terms: tuple[str, ...]
    lines: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class IndexSearchResult:
    status: IndexStatus
    matches: tuple[IndexMatch, ...]


class LocalSourceIndex:
    """Own project observations, lexical postings and event acknowledgement.

    Native events are advisory: startup, coverage loss, policy changes and periodic
    reconciliation re-read content. Each search result is read and version-checked before
    release. Generations describe a drained observation, not a filesystem transaction.
    Index data remains in memory and is never sent to a service or persisted.
    """

    _WORD = re.compile(r"\w+", re.UNICODE)
    _CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[_\W]+")

    def __init__(
        self,
        scope: ProjectSourceScope,
        policy: IndexInclusionPolicy,
        *,
        journal: ChangeJournal | None = None,
        native_watch: bool = True,
        reconcile_interval: float = 60.0,
        max_text_bytes: int = 2 * 1024 * 1024,
        encoding: str = "utf-8",
    ):
        if not math.isfinite(reconcile_interval) or reconcile_interval <= 0 or max_text_bytes < 1:
            raise ValueError("Index reconciliation interval and text size limit must be positive and finite")
        self.scope = scope
        self._policy = policy
        self._journal = journal
        self._native_watch = native_watch
        self._interval = reconcile_interval
        self._max_text_bytes = max_text_bytes
        self._encoding = encoding
        self._lock = threading.RLock()
        self._observation: IndexObservation | None = None
        self._postings: dict[str, frozenset[str]] = {}
        self._signature: str | None = None
        self._reconciled_monotonic = 0.0
        self._force_reconcile = True
        self._has_aliases = False
        self._watch_attempted = journal is not None
        self._owns_native_watch = journal is None and native_watch
        self._watch_failure: str | None = None
        self._finalizer = None if journal is None else weakref.finalize(self, journal.close)
        self._closed = False

    @classmethod
    def terms(cls, text: str) -> frozenset[str]:
        """Extract case-insensitive words and identifier components without remote models."""
        result = set()
        for word in cls._WORD.findall(text):
            if len(word) <= 128:
                result.add(word.casefold())
                result.update(part.casefold() for part in cls._CAMEL.split(word) if part)
        return frozenset(result)

    def _start_watch(self) -> None:
        if self._watch_attempted or not self._native_watch:
            return
        self._watch_attempted = True
        try:
            self._watch_failure = NativeWatchCoverage.reconciliation_reason(self.scope.root, self._policy)
            if self._watch_failure is not None:
                return
            if sys.platform == "darwin":
                from selene.indexing.kqueue import KqueueJournal

                self._journal = KqueueJournal(self.scope.root, self._policy)
            elif sys.platform == "linux":
                from selene.indexing.inotify import InotifyJournal

                self._journal = InotifyJournal(self.scope.root, self._policy)
            else:
                self._watch_failure = "unsupported_native_watcher"
            if self._journal is not None:
                self._finalizer = weakref.finalize(self, self._journal.close)
        except (OSError, WatchUnavailable):
            self._watch_failure = "native_watch_unavailable"

    def _drop_watch(self, reason: str = "native_watch_unavailable") -> None:
        if self._finalizer is not None:
            self._finalizer()
            self._finalizer = None
        self._journal = None
        self._watch_failure = reason
        self._force_reconcile = True

    def _changes(self) -> ChangeBatch:
        if self._journal is not None:
            try:
                return self._journal.read()
            except (OSError, WatchUnavailable):
                self._drop_watch()
        return ChangeBatch(0, frozenset(), True, (self._watch_failure or "content_reconciliation_mode",))

    @staticmethod
    def _policy_event(path: str) -> bool:
        return Path(path).name == ".gitignore" or path in {".git/HEAD", ".git/index", ".git/info/exclude", ".git"}

    def _capture(self, path: str) -> IndexedFile | None:
        try:
            canonical = self.scope.resolve(path).relative_to(self.scope.root).as_posix()
            if not self._policy.includes(path, directory=False) or not self._policy.includes(canonical, directory=False):
                return None
            if not self.scope.resolve(path).is_file():
                return None
            if self.scope.stamp(path).size > self._max_text_bytes:
                return IndexedFile(path, canonical, self.scope.fingerprint(path), self._policy.is_source(path), frozenset(), "size_limit")
            snapshot = self.scope.read(path, max_bytes=self._max_text_bytes)
            if self.scope.resolve(path).relative_to(self.scope.root).as_posix() != canonical:
                raise FileSnapshotConflict("Source alias changed while indexing")
            try:
                text = snapshot.content.decode(self._encoding)
                status = "binary" if "\0" in text else "indexed"
            except UnicodeDecodeError:
                text, status = "", "encoding_unsupported"
            terms = self.terms(text) | self.terms(path) if status == "indexed" else frozenset()
            return IndexedFile(path, canonical, snapshot.sha256, self._policy.is_source(path), terms, status)
        except (FileNotFoundError, SourceScopeError):
            return None

    def _commit(
        self,
        files: dict[str, IndexedFile],
        issues: tuple[ScopeIssue, ...],
        reasons: set[str],
        full: bool,
    ) -> None:
        previous = self._observation
        old_files = {} if previous is None else previous.files
        changed = {path for path in files.keys() | old_files.keys() if files.get(path) != old_files.get(path)}
        if changed or previous is None:
            # replace only affected postings; no content is re-read for unchanged documents
            updates: dict[str, set[str]] = {}
            for path in changed:
                previous_entry, next_entry = old_files.get(path), files.get(path)
                if previous_entry is not None:
                    for term in previous_entry.terms:
                        if term not in updates:
                            updates[term] = set(self._postings.get(term, ()))
                        updates[term].discard(path)
                if next_entry is not None:
                    for term in next_entry.terms:
                        if term not in updates:
                            updates[term] = set(self._postings.get(term, ()))
                        updates[term].add(path)
            postings = self._postings.copy()
            for term, paths in updates.items():
                if paths:
                    postings[term] = frozenset(paths)
                else:
                    postings.pop(term, None)
            self._postings = postings
            file_map: Mapping[str, IndexedFile] = MappingProxyType(files)
            source_fingerprints: Mapping[str, str] = MappingProxyType(
                {path: f"{entry.sha256}:{entry.canonical_path}" for path, entry in files.items() if entry.source}
            )
        else:
            file_map, source_fingerprints = previous.files, previous.source_fingerprints
        now = time.time()
        if full:
            self._reconciled_monotonic = time.monotonic()
        status = IndexStatus(
            (0 if previous is None else previous.status.generation) + int(bool(changed) or previous is None),
            now,
            now if full or previous is None else previous.status.reconciled_at,
            "reconciliation" if self._journal is None else type(self._journal).__name__,
            True,
            tuple(sorted(reasons)),
            len(files),
            sum(entry.text_status == "indexed" for entry in files.values()),
            issues,
        )
        self._observation = IndexObservation(status, file_map, source_fingerprints)

    def refresh(self, *, reconcile: bool = False) -> IndexObservation:
        """Drain changes and return a content-versioned observation, or raise if still changing."""
        with self._lock:
            if self._closed:
                raise RuntimeError("The project index is closed")
            self.scope.validate_root()
            if self._observation is None:
                self._policy.refresh()
                self._start_watch()
            self._force_reconcile |= reconcile
            reasons: set[str] = set()
            for _ in range(3):
                CancellationToken.check_current()
                batch = self._changes()
                signature = self._policy.signature()
                full = (
                    self._force_reconcile
                    or batch.reconcile
                    or signature != self._signature
                    or time.monotonic() - self._reconciled_monotonic >= self._interval
                    or any(self._policy_event(path) for path in batch.paths)
                    or (self._has_aliases and bool(batch.paths))
                    or any((self.scope.root / path).is_symlink() for path in batch.paths)
                )
                if not full and not batch.paths:
                    assert self._observation is not None
                    self._observation = replace(self._observation, status=replace(self._observation.status, observed_at=time.time()))
                    return self._observation
                reasons.update(batch.reasons)
                if full:
                    # a failed/cancelled scan must retain the need to reconcile even if watches are rebuilt
                    self._force_reconcile = True
                    reasons.add("content_reconciliation")
                    self._policy.refresh()
                    signature = self._policy.signature()
                    if self._journal is not None:
                        try:
                            coverage_issue = (
                                NativeWatchCoverage.reconciliation_reason(self.scope.root, self._policy)
                                if self._owns_native_watch
                                else None
                            )
                            if coverage_issue:
                                self._drop_watch(coverage_issue)
                            else:
                                self._journal.rebuild()
                        except (OSError, WatchUnavailable):
                            self._drop_watch()
                    batch = self._changes()
                    reasons.update(batch.reasons)
                    tree = self.scope.scan(self._policy)
                    paths, issues = tree.files, tree.issues
                    files = {}
                    self._has_aliases = tree.has_aliases
                else:
                    assert self._observation is not None
                    paths, issues = tuple(sorted(batch.paths)), self._observation.status.issues
                    files = dict(self._observation.files)
                for path in paths:
                    CancellationToken.check_current()
                    entry = self._capture(path)
                    if entry is None:
                        files.pop(path, None)
                    else:
                        files[path] = entry
                CancellationToken.check_current()
                self.scope.validate_root()
                self._commit(files, issues, reasons, full)
                self._signature = signature
                self._force_reconcile = False
                if self._journal is None:
                    assert self._observation is not None
                    return self._observation
                self._journal.acknowledge(batch.cursor)
                pending = self._changes()
                if not pending.paths and not pending.reconcile:
                    assert self._observation is not None
                    return self._observation
            raise IndexCatchingUp("Project changes are still arriving; retry after writes settle")

    def record_local_write(self, relative_path: str) -> None:
        """Record a Selene edit without waiting for an external event delivery mechanism."""
        path = self.scope.normalize(relative_path)
        with self._lock:
            if self._journal is not None:
                self._journal.record_local_write(path)
            else:
                self._force_reconcile = True

    def search(self, query: str, *, relative_path: str = "", limit: int = 10, reconcile: bool = False) -> IndexSearchResult:
        """Return ranked lexical matches with freshly checked hashes and 1-based source lines."""
        terms = self.terms(query)
        if not terms or len(terms) > 64 or not 1 <= limit <= 50:
            raise ValueError("Use 1-64 search terms and a result limit between 1 and 50")
        prefix = self.scope.normalize(relative_path)
        with self._lock:
            for _ in range(3):
                observation = self.refresh(reconcile=reconcile)
                candidates: dict[str, set[str]] = {}
                for term in terms:
                    for path in self._postings.get(term, ()):
                        if not prefix or path == prefix or path.startswith(prefix + "/"):
                            candidates.setdefault(path, set()).add(term)
                ranked = sorted(candidates, key=lambda path: (-len(candidates[path]), -len(terms & self.terms(path)), path))[:limit]
                matches = []
                changed = False
                for path in ranked:
                    CancellationToken.check_current()
                    try:
                        snapshot = self.scope.read(path, max_bytes=self._max_text_bytes)
                        if snapshot.sha256 != observation.files[path].sha256:
                            raise FileSnapshotConflict("Search candidate changed")
                    except (FileNotFoundError, FileSnapshotConflict, SourceScopeError):
                        self.record_local_write(path)
                        changed = True
                        break
                    lines = tuple(
                        (number, line[:1000])
                        for number, line in enumerate(
                            snapshot.content.decode(self._encoding).replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1
                        )
                        if self.terms(line) & terms
                    )[:3]
                    matches.append(IndexMatch(path, snapshot.sha256, tuple(sorted(candidates[path])), lines))
                if not changed:
                    return IndexSearchResult(observation.status, tuple(matches))
            raise IndexCatchingUp("Search candidates changed repeatedly; retry after writes settle")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._finalizer is not None:
                self._finalizer()
                self._finalizer = None
