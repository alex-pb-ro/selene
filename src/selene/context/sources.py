"""Version-checked project source capture; complete bodies live only within a request."""

from dataclasses import dataclass
from pathlib import Path

from selene.context.model import ContextLimitReached, ContextRole, ContextSourceVersion, SourceReference, StaleContextError
from selene.indexing.local_index import IndexObservation, LocalSourceIndex
from selene.indexing.scope import SourceRootReplaced, SourceScopeError
from selene.util.cancellation import CancellationToken
from selene.util.file_snapshot import FileSnapshotConflict


@dataclass(frozen=True)
class ContextDocument:
    path: str
    canonical_path: str
    sha256: str
    lines: tuple[str, ...]

    def reference(self, start_line: int = 1, end_line: int | None = None, symbol: str = "") -> SourceReference:
        last = len(self.lines) if end_line is None else end_line
        if start_line < 1 or last > len(self.lines) or last < start_line:
            raise ValueError("The source range is outside the captured document")
        return SourceReference(self.path, self.sha256, start_line, last, symbol)

    def excerpt(self, reference: SourceReference) -> str:
        if reference.path != self.path or reference.sha256 != self.sha256:
            raise StaleContextError("The source reference does not match the captured document")
        self.reference(reference.start_line, reference.end_line)
        return "\n".join(self.lines[reference.start_line - 1 : reference.end_line])


class ContextSources:
    """Own one request's validated source bodies and expose only indexed project paths."""

    def __init__(self, index: LocalSourceIndex, observation: IndexObservation, encoding: str, *, max_files: int = 48):
        if max_files < 1:
            raise ValueError("The context source-file allowance must be positive")
        self.index = index
        self.observation = observation
        self._encoding = encoding
        self._max_files = max_files
        self._documents: dict[str, ContextDocument] = {}

    def contains(self, path: str) -> bool:
        normalized = self.index.scope.normalize(path)
        entry = self.observation.files.get(normalized)
        return entry is not None and entry.text_status == "indexed"

    def read(self, path: str) -> ContextDocument:
        CancellationToken.check_current()
        path = self.index.scope.normalize(path)
        if path in self._documents:
            return self._documents[path]
        entry = self.observation.files.get(path)
        if entry is None or entry.text_status != "indexed":
            raise ValueError("Context sources must be searchable files included in the active project index")
        if len(self._documents) >= self._max_files:
            raise ContextLimitReached("Context source-file limit reached")
        try:
            snapshot = self.index.scope.read(path, max_bytes=2 * 1024 * 1024)
            canonical = self.index.scope.resolve(path).relative_to(self.index.scope.root).as_posix()
            if snapshot.sha256 != entry.sha256 or canonical != entry.canonical_path:
                raise FileSnapshotConflict("Context source changed during capture")
        except (OSError, SourceScopeError, SourceRootReplaced, FileSnapshotConflict) as error:
            self.index.record_local_write(path)
            raise StaleContextError(f"Context source changed: {path}") from error
        text = snapshot.content.decode(self._encoding).replace("\r\n", "\n").replace("\r", "\n")
        document = ContextDocument(path, canonical, snapshot.sha256, tuple(text.split("\n")))
        self._documents[path] = document
        return document

    def versions(self) -> tuple[ContextSourceVersion, ...]:
        """Return version metadata without retaining source bodies beyond the request."""
        return tuple(ContextSourceVersion(document.path, document.canonical_path, document.sha256) for document in self._documents.values())

    def validate(self) -> None:
        """Reject a selection whose participating sources or inclusion rules changed."""
        self.validate_versions(self.versions(), self.observation.status.generation)

    def validate_versions(self, versions: tuple[ContextSourceVersion, ...], generation: int) -> None:
        """Check selection generation and directly hash every participating source."""
        current = self.index.refresh()
        if current.status.generation != generation:
            raise StaleContextError("The project index generation changed; request a new context bundle")
        for version in versions:
            CancellationToken.check_current()
            path, canonical, sha256 = version.path, version.canonical_path, version.sha256
            entry = current.files.get(path)
            if entry is None or entry.canonical_path != canonical or entry.sha256 != sha256:
                raise StaleContextError(f"Context source changed or became excluded: {path}")
            try:
                if (
                    self.index.scope.fingerprint(path) != sha256
                    or self.index.scope.resolve(path).relative_to(self.index.scope.root).as_posix() != canonical
                ):
                    raise FileSnapshotConflict("Context source identity changed")
            except (OSError, SourceScopeError, SourceRootReplaced, FileSnapshotConflict) as error:
                self.index.record_local_write(path)
                raise StaleContextError(f"Context source changed: {path}") from error


class ContextFileRoles:
    """Classify retrieval roles without claiming that naming conventions prove behavior."""

    @staticmethod
    def classify(path: str) -> ContextRole:
        value = Path(path)
        parts = {part.casefold() for part in value.parts}
        name = value.name.casefold()
        if (
            parts & {"test", "tests", "__tests__", "spec", "specs"}
            or name.startswith("test_")
            or any(marker in name for marker in (".test.", ".spec.", "_test."))
        ):
            return "test"
        if value.suffix.casefold() in {".md", ".rst", ".txt", ".adoc"} or name.startswith(("readme", "changelog")):
            return "documentation"
        if value.suffix.casefold() in {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"} or name.startswith(".env"):
            return "configuration"
        return "code"
