"""Bounded composition of existing language-server symbol and reference operations."""

import io
import keyword
import math
import re
import time
import tokenize
from collections.abc import Callable
from concurrent.futures import CancelledError
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Protocol, TypeVar

from selene.context.model import ContextLimitReached, SemanticEdge, SemanticNode, SourceReference, StaleContextError
from selene.context.python_bindings import PythonImportBindings
from selene.context.sources import ContextDocument, ContextSources
from selene.indexing.scope import SourceScopeError
from selene.symbol import LanguageServerSymbol, LanguageServerSymbolRetriever
from selene.util.cancellation import CancellationToken
from solidlsp.ls_types import Location

if TYPE_CHECKING:
    from selene.project import Project

T = TypeVar("T")


class ContextSemanticProvider(Protocol):
    """Supply source-bound semantic relationships without returning cached source bodies."""

    def symbols(self, path: str, pattern: str = "") -> tuple[SemanticNode, ...]: ...

    def at_line(self, path: str, line: int, column: int = 0) -> SemanticNode | None: ...

    def dependencies(self, node: SemanticNode) -> tuple[SemanticEdge, ...]: ...

    def references(self, node: SemanticNode) -> tuple[SemanticEdge, ...]: ...

    def limitations(self) -> tuple[str, ...]: ...

    def calls_used(self) -> int: ...


class IdentifierPositions:
    """Find bounded candidate identifier positions; only LSP resolution establishes an edge."""

    _NAME = re.compile(r"[^\W\d]\w*", re.UNICODE)
    _SKIP = frozenset(keyword.kwlist) | {
        "const",
        "let",
        "var",
        "function",
        "new",
        "this",
        "null",
        "undefined",
        "true",
        "false",
        "export",
        "default",
        "interface",
        "type",
        "public",
        "private",
        "protected",
        "static",
        "async",
        "await",
        "self",
        "cls",
    }

    @dataclass(frozen=True)
    class Position:
        name: str
        line: int
        column: int
        priority: int

    @classmethod
    def collect(cls, document: ContextDocument, reference: SourceReference, *, limit: int = 12) -> tuple[Position, ...]:
        start, end = reference.start_line - 1, min(reference.end_line, reference.start_line + 199)
        found = []
        if document.path.endswith(".py"):
            try:
                tokens = tokenize.generate_tokens(io.StringIO("\n".join(document.lines)).readline)
                for index, token in enumerate(tokens):
                    if index % 100 == 0:
                        CancellationToken.check_current()
                    if token.start[0] > end:
                        break
                    if token.type == tokenize.NAME and start <= token.start[0] - 1 < end:
                        found.append((token.string, token.start[0] - 1, token.start[1]))
            except (tokenize.TokenError, IndentationError):
                pass
        else:
            for line in range(start, end):
                CancellationToken.check_current()
                found.extend((match.group(), line, match.start()) for match in cls._NAME.finditer(document.lines[line]))
        positions = []
        for name, line, column in found:
            if name in cls._SKIP:
                continue
            text = document.lines[line]
            suffix = text[column + len(name) :].lstrip()
            priority = 0 if suffix.startswith("(") or name[:1].isupper() else 1
            utf16_column = len(text[:column].encode("utf-16-le")) // 2
            positions.append(cls.Position(name, line, utf16_column, priority))
        selected = []
        names = set()
        for position in sorted(positions, key=lambda value: (value.priority, value.line, value.column)):
            if position.name not in names:
                selected.append(position)
                names.add(position.name)
            if len(selected) >= limit:
                break
        return tuple(selected)


class LanguageServerContextProvider:
    """Resolve a bounded number of symbol relationships using the active project backend.

    The time allowance is checked between logical operations; a backend request already
    executing follows its own timeout and the executor's cancellation ownership rules.
    """

    def __init__(self, project: "Project", sources: ContextSources, *, max_calls: int = 40, seconds: float = 10.0):
        if max_calls < 1 or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Semantic operation and time allowances must be positive and finite")
        self._sources = sources
        self._limit = max_calls
        self._deadline = time.monotonic() + seconds
        self._calls = 0
        self._limitations: set[str] = {"language_server_relationships_are_static_not_runtime_guarantees"}
        self._retriever = None
        if project.language_backend.is_lsp() and project.language_server_manager is not None:
            self._retriever = LanguageServerSymbolRetriever(project)
        else:
            self._limitations.add("semantic_backend_unavailable")

    def _call(self, operation: Callable[[], T]) -> T | None:
        CancellationToken.check_current()
        if self._calls >= self._limit or time.monotonic() >= self._deadline:
            self._limitations.add("semantic_operation_budget_exhausted")
            return None
        self._calls += 1
        try:
            result = operation()
        except (CancelledError, StaleContextError, ContextLimitReached):
            raise
        except Exception:
            CancellationToken.check_current()
            self._limitations.add("semantic_operation_failed")
            return None
        CancellationToken.check_current()
        return result

    def _node(self, symbol: LanguageServerSymbol) -> SemanticNode | None:
        path = symbol.relative_path
        try:
            included = path is not None and self._sources.contains(path)
        except SourceScopeError:
            included = False
        if not included or path is None:
            self._limitations.add("out_of_scope_or_unsearchable_semantic_targets_omitted")
            return None
        document = self._sources.read(path)
        start = symbol.body_start_position
        end = symbol.body_end_position
        if start is None or end is None or symbol.line is None or symbol.column is None:
            self._limitations.add("symbols_without_source_ranges_omitted")
            return None
        first = start["line"] + 1
        last = max(first, end["line"] + int(end["character"] > 0))
        if last > len(document.lines):
            self._limitations.add("invalid_semantic_ranges_omitted")
            return None
        parent = symbol.get_parent()
        return SemanticNode(
            document.reference(first, last, symbol.get_name_path()),
            symbol.symbol_kind_name,
            symbol.line,
            symbol.column,
            None if parent is None else parent.symbol_kind_name,
        )

    def _can_analyze(self, path: str) -> bool:
        if self._retriever is None or not self._retriever.can_analyze_file(path):
            self._limitations.add("some_files_have_no_semantic_backend")
            return False
        self._sources.read(path)
        return True

    def _location_path(self, location: Location) -> str | None:
        """Map a backend location through canonical indexed paths, including aliased project roots."""
        path = self._sources.resolve_indexed_path(location["absolutePath"])
        if path is None:
            self._limitations.add("out_of_scope_or_unsearchable_semantic_targets_omitted")
        return path

    def symbols(self, path: str, pattern: str = "") -> tuple[SemanticNode, ...]:
        if not self._can_analyze(path):
            return ()
        assert self._retriever is not None
        if pattern:
            symbols = self._call(partial(self._retriever.find, pattern, within_relative_path=path))
        else:
            server = self._retriever.get_language_server(path)
            document_symbols = self._call(partial(server.request_document_symbols, path))
            symbols = (
                None
                if document_symbols is None
                else [LanguageServerSymbol(symbol) for symbol in document_symbols.get_all_symbols_and_roots()[0]]
            )
        if symbols is None:
            return ()
        nodes = []
        for symbol in symbols:
            CancellationToken.check_current()
            node = self._node(symbol)
            if node is not None:
                nodes.append(node)
            if len(nodes) >= 40:
                self._limitations.add("per_file_symbol_limit_reached")
                break
        return tuple(nodes)

    def at_line(self, path: str, line: int, column: int = 0) -> SemanticNode | None:
        if not self._can_analyze(path):
            return None
        assert self._retriever is not None
        server = self._retriever.get_language_server(path)
        result = self._call(lambda: server.request_symbol_at_location(path, line - 1, column, include_body=False))
        return None if result is None else self._node(LanguageServerSymbol(result))

    def dependencies(self, node: SemanticNode) -> tuple[SemanticEdge, ...]:
        path = node.reference.path
        if not self._can_analyze(path):
            return ()
        assert self._retriever is not None
        server = self._retriever.get_language_server(path)
        document = self._sources.read(path)
        edges = []
        seen = set()
        for position in IdentifierPositions.collect(document, node.reference):
            if position.line == node.declaration_line and position.column == node.declaration_column:
                continue
            locations = self._call(partial(server.request_definition, path, position.line, position.column))
            for index, location in enumerate(locations or ()):
                CancellationToken.check_current()
                if index >= 32:
                    self._limitations.add("definition_location_limit_reached")
                    break
                target_path = self._location_path(location)
                if target_path is None:
                    continue
                if target_path == path and node.reference.start_line <= location["range"]["start"]["line"] + 1 <= node.reference.end_line:
                    continue
                target = self.at_line(target_path, location["range"]["start"]["line"] + 1, location["range"]["start"]["character"])
                if target is None or target.reference in seen:
                    continue
                if target.reference.path == path and node.reference.start_line <= target.reference.start_line <= node.reference.end_line:
                    continue
                seen.add(target.reference)
                site = document.reference(position.line + 1, position.line + 1)
                edges.append(SemanticEdge(target, node.reference, "definition_of_reference", site, position.column))
        return tuple(edges)

    def references(self, node: SemanticNode) -> tuple[SemanticEdge, ...]:
        return self._related_locations(node, preserve_sites=False)

    def reference_sites(self, node: SemanticNode) -> tuple[SemanticEdge, ...]:
        """Preserve separate reference sites within the same enclosing symbol."""
        return self._related_locations(node, preserve_sites=True)

    def implementations(self, node: SemanticNode) -> tuple[SemanticEdge, ...]:
        """Resolve bounded implementations, recording failed or unsupported requests."""
        return self._related_locations(node, preserve_sites=True, implementations=True)

    def _related_locations(self, node: SemanticNode, *, preserve_sites: bool, implementations: bool = False) -> tuple[SemanticEdge, ...]:
        path = node.reference.path
        if not self._can_analyze(path):
            return ()
        assert self._retriever is not None
        server = self._retriever.get_language_server(path)
        operation = server.request_implementation if implementations else server.request_references
        locations = self._call(partial(operation, path, node.declaration_line, node.declaration_column))
        if locations is None and implementations:
            self._limitations.add("implementation_query_unavailable_or_failed")
        edges = []
        seen = set()
        for index, location in enumerate(locations or ()):
            CancellationToken.check_current()
            if len(edges) >= 12 or index >= 64:
                self._limitations.add("reference_limit_reached")
                break
            target_path = self._location_path(location)
            if target_path is None:
                continue
            line = location["range"]["start"]["line"] + 1
            target = self.at_line(target_path, line, location["range"]["start"]["character"])
            if target is None and preserve_sites and not implementations:
                target = PythonImportBindings.at_reference(
                    self._sources.read(target_path), line - 1, location["range"]["start"]["character"]
                )
            if target is None or target.reference == node.reference:
                continue
            site = self._sources.read(target_path).reference(line, line)
            key = (target.reference, site, location["range"]["start"]["character"]) if preserve_sites else target.reference
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                SemanticEdge(
                    target,
                    node.reference,
                    "implementation_of_symbol"
                    if implementations
                    else "import_alias_binding"
                    if target.kind == "ImportAlias"
                    else "reference_to_symbol",
                    site,
                    location["range"]["start"]["character"],
                )
            )
        return tuple(edges)

    def limitations(self) -> tuple[str, ...]:
        return tuple(sorted(self._limitations))

    def calls_used(self) -> int:
        return self._calls
