"""Bounded mapping from changed ranges to static references and implementations."""

from collections import deque
from typing import Protocol

from selene.changes.model import MaterializedFileChange
from selene.context.model import ContextLimitReached, SemanticEdge, SemanticNode
from selene.context.semantic import ContextSemanticProvider
from selene.context.sources import ContextFileRoles, ContextSources
from selene.impact.model import ChangedSymbol, ImpactFinding, ImpactUncertainty
from selene.util.cancellation import CancellationToken


class ImpactSemanticProvider(ContextSemanticProvider, Protocol):
    def reference_sites(self, node: SemanticNode) -> tuple[SemanticEdge, ...]: ...

    def implementations(self, node: SemanticNode) -> tuple[SemanticEdge, ...]: ...


class ImpactGraph:
    """Keep proven static relationships separate from runtime impact claims."""

    _API_KINDS = {"Function", "Method", "Class", "Interface", "Struct", "Enum", "Property", "Field", "Constant", "Variable"}

    @classmethod
    def _api_symbol(cls, node: SemanticNode) -> bool:
        return node.kind in cls._API_KINDS and not (
            node.kind == "Variable" and node.container_kind in {"Function", "Method", "Constructor"}
        )

    def __init__(self, sources: ContextSources, semantics: ImpactSemanticProvider, scope: str, *, max_depth: int = 2):
        self.sources = sources
        self.semantics = semantics
        self.scope = sources.index.scope.normalize(scope)
        self.max_depth = max_depth
        self.changed_symbols: list[ChangedSymbol] = []
        self.findings: list[ImpactFinding] = []
        self.uncertainties: list[ImpactUncertainty] = []

    def in_scope(self, path: str) -> bool:
        return not self.scope or path == self.scope or path.startswith(self.scope + "/")

    def _seeds(self, change: MaterializedFileChange) -> tuple[SemanticNode, ...]:
        if change.kind == "create":
            self.uncertainties.append(
                ImpactUncertainty(
                    "new_source_not_analyzed_by_current_language_server",
                    "Validate new declarations and imports after applying the proposed change.",
                )
            )
            return ()
        symbols = self.semantics.symbols(change.path)
        nodes = []
        for span in change.ranges:
            candidates = [
                node
                for node in symbols
                if self._api_symbol(node) and node.reference.start_line - 1 < span.old_end and node.reference.end_line > span.old_start
            ]
            insertion = span.old_start == span.old_end
            if insertion:
                candidates = [
                    node
                    for node in symbols
                    if self._api_symbol(node) and node.reference.start_line - 1 <= span.old_start <= node.reference.end_line
                ]
            # select every directly touched symbol, omitting a container when only its child overlaps
            selected = [
                node
                for node in candidates
                if span.old_start <= node.declaration_line < span.old_end
                or not any(
                    other != node
                    and node.reference.start_line <= other.reference.start_line
                    and node.reference.end_line >= other.reference.end_line
                    for other in candidates
                )
            ]
            for node in selected:
                if node not in nodes:
                    nodes.append(node)
                    self.changed_symbols.append(
                        ChangedSymbol(node.reference, "adjacent_to_insertion" if insertion else "overlapping_changed_lines")
                    )
        if not nodes:
            document = self.sources.read(change.path)
            self.uncertainties.append(
                ImpactUncertainty(
                    "changed_lines_have_no_resolved_api_symbol",
                    "Review file-level initialization, data changes and lexical candidates.",
                    document.reference(1, min(13, len(document.lines))),
                )
            )
        return tuple(nodes)

    def analyze(self, changes: tuple[MaterializedFileChange, ...]) -> None:
        pending = deque()
        try:
            for change in changes:
                for node in self._seeds(change):
                    pending.append((node, (), 0))
            visited = set()
            finding_keys = set()
            while pending and len(visited) < 24:
                CancellationToken.check_current()
                node, via, depth = pending.popleft()
                if node.reference in visited:
                    continue
                visited.add(node.reference)
                if depth >= self.max_depth:
                    self.uncertainties.append(
                        ImpactUncertainty(
                            "transitive_depth_limit_reached",
                            "Analyze the returned boundary symbols or request a larger depth.",
                            node.reference,
                        )
                    )
                    continue
                edges = self.semantics.reference_sites(node)
                if depth == 0 and node.kind in {"Class", "Interface", "Method", "Function", "Property"}:
                    edges += self.semantics.implementations(node)
                for edge in edges:
                    if len(self.findings) >= 128:
                        break
                    next_depth = depth if edge.kind == "import_alias_binding" else depth + 1
                    if not self.in_scope(edge.target.reference.path):
                        self.uncertainties.append(
                            ImpactUncertainty(
                                "relationship_outside_requested_scope", "Repeat analysis with a wider project scope.", node.reference
                            )
                        )
                        pending.append((edge.target, via + (node.reference,), next_depth))
                        continue
                    key = (edge.origin, edge.target.reference, edge.site, edge.site_column, edge.kind)
                    if key in finding_keys:
                        continue
                    finding_keys.add(key)
                    role = ContextFileRoles.classify(edge.target.reference.path)
                    if edge.kind == "implementation_of_symbol":
                        role = "implementation"
                    elif edge.kind == "import_alias_binding":
                        role = "import_binding"
                    elif edge.target.kind == "Interface" or edge.target.container_kind == "Interface":
                        role = "interface"
                    elif role == "code":
                        role = "referencing_symbol"
                    self.findings.append(
                        ImpactFinding(
                            edge.target.reference,
                            role,
                            edge.kind,
                            "language_server",
                            edge.origin,
                            edge.site,
                            next_depth,
                            via,
                            edge.site_column,
                        )
                    )
                    pending.append((edge.target, via + (node.reference,), next_depth))
                if len(self.findings) >= 128:
                    break
            if pending:
                self.uncertainties.append(
                    ImpactUncertainty(
                        "graph_traversal_limit_reached", "Narrow the changed-file set or inspect the remaining boundary symbols."
                    )
                )
        except ContextLimitReached:
            self.uncertainties.append(ImpactUncertainty("source_file_limit_reached", "Narrow the analysis scope and repeat the request."))
