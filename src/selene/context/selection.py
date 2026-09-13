"""Role-diverse context selection with explicit semantic and heuristic provenance."""

from collections import deque
from dataclasses import replace

from selene.context.model import ContextAnchor, ContextCandidate, ContextEvidence, ContextLimitReached, ContextRole, SemanticNode
from selene.context.semantic import ContextSemanticProvider
from selene.context.sources import ContextFileRoles, ContextSources
from selene.indexing.local_index import LocalSourceIndex
from selene.util.cancellation import CancellationToken


class ContextCandidatePool:
    """Deduplicate overlapping source ranges and prioritize distinct retrieval roles."""

    _ROLES: tuple[ContextRole, ...] = ("dependency", "test", "documentation", "configuration", "type", "caller", "code")

    def __init__(self, limit: int = 64):
        if limit < 1:
            raise ValueError("The context candidate allowance must be positive")
        self._limit = limit
        self._candidates: list[ContextCandidate] = []
        self.limited = False

    def add(self, candidate: ContextCandidate) -> None:
        retained = []
        pending = list(self._candidates)
        while pending:
            existing = pending.pop()
            left, right = existing.reference, candidate.reference
            if (
                existing.canonical_path != candidate.canonical_path
                or left.sha256 != right.sha256
                or left.end_line < right.start_line
                or right.end_line < left.start_line
            ):
                retained.append(existing)
                continue
            # preserve the more specific higher-priority anchor when a broad match contains it
            best = min((existing, candidate), key=lambda item: (item.priority, item.reference.end_line - item.reference.start_line))
            contained = (left.start_line <= right.start_line and left.end_line >= right.end_line) or (
                right.start_line <= left.start_line and right.end_line >= left.end_line
            )
            if contained and best.reference.symbol:
                reference = best.reference
            else:
                reference = replace(
                    best.reference,
                    start_line=min(left.start_line, right.start_line),
                    end_line=max(left.end_line, right.end_line),
                    symbol="",
                )
            candidate = replace(
                best,
                reference=reference,
                roles=tuple(sorted(set(existing.roles + candidate.roles))),
                evidence=tuple(dict.fromkeys(existing.evidence + candidate.evidence)),
            )
            # recheck prior ranges after a merge expands the candidate's interval
            pending.extend(retained)
            retained = []
        retained.append(candidate)
        retained.sort(key=lambda item: (item.priority, item.reference.path, item.reference.start_line))
        self.limited |= len(retained) > self._limit
        self._candidates = retained[: self._limit]

    def ordered(self) -> tuple[ContextCandidate, ...]:
        anchors = [candidate for candidate in self._candidates if "anchor" in candidate.roles]
        remaining = [candidate for candidate in self._candidates if "anchor" not in candidate.roles]
        queues = {role: deque(candidate for candidate in remaining if role in candidate.roles) for role in self._ROLES}
        result = list(anchors)
        seen = set(anchors)
        while any(queues.values()):
            for role in self._ROLES:
                if queues[role]:
                    candidate = queues[role].popleft()
                    if candidate not in seen:
                        result.append(candidate)
                        seen.add(candidate)
        return tuple(result)


class ContextSelector:
    """Compose anchors, lexical retrieval and bounded semantic expansion for one request."""

    def __init__(self, sources: ContextSources, semantics: ContextSemanticProvider, scope: str):
        self.sources = sources
        self.semantics = semantics
        self.scope = sources.index.scope.normalize(scope)
        self._pool = ContextCandidatePool()
        self._limitations: set[str] = {"bounded_selection_not_exhaustive", "file_role_names_are_heuristics"}

    def _in_scope(self, path: str) -> bool:
        return not self.scope or path == self.scope or path.startswith(self.scope + "/")

    def _add(self, node: SemanticNode, role: ContextRole, evidence: ContextEvidence, priority: int) -> None:
        path = node.reference.path
        if not self._in_scope(path):
            self._limitations.add("relationships_outside_requested_scope_omitted")
            return
        document = self.sources.read(path)
        roles = {role, ContextFileRoles.classify(path)}
        if node.kind in {"Class", "Interface", "Struct", "Enum", "TypeParameter"}:
            roles.add("type")
        self._pool.add(ContextCandidate(node.reference, document.canonical_path, tuple(sorted(roles)), (evidence,), priority))

    def _excerpt(self, path: str, terms: frozenset[str], role: ContextRole, evidence: ContextEvidence, priority: int) -> None:
        if not self._in_scope(path):
            return
        document = self.sources.read(path)
        best_line, best_score = 0, -1
        for line, text in enumerate(document.lines):
            if line % 100 == 0:
                CancellationToken.check_current()
            score = len(LocalSourceIndex.terms(text) & terms)
            if score > best_score:
                best_line, best_score = line, score
        reference = document.reference(max(1, best_line - 2), min(len(document.lines), best_line + 13))
        roles = tuple(sorted({role, ContextFileRoles.classify(path)}))
        self._pool.add(ContextCandidate(reference, document.canonical_path, roles, (evidence,), priority))

    def select(self, query: str, anchors: tuple[ContextAnchor, ...]) -> tuple[ContextCandidate, ...]:
        terms = LocalSourceIndex.terms(query)
        seeds: list[SemanticNode] = []
        try:
            # give explicit file and symbol anchors priority over inferred relationships
            for anchor in anchors:
                path = self.sources.index.scope.normalize(anchor.path)
                if not self._in_scope(path):
                    raise ValueError("An anchor is outside the requested context scope")
                self.sources.read(path)
                nodes = self.semantics.symbols(path, anchor.symbol)
                if not anchor.symbol:
                    nodes = tuple(
                        sorted(
                            nodes,
                            key=lambda node: (
                                -len(LocalSourceIndex.terms(node.reference.symbol) & terms),
                                node.reference.start_line,
                                node.reference.end_line - node.reference.start_line,
                            ),
                        )
                    )[:2]
                if not nodes:
                    if anchor.symbol:
                        self._limitations.add("requested_symbol_could_not_be_resolved")
                    self._excerpt(path, terms, "anchor", ContextEvidence("requested_path", "requested"), 0)
                for node in nodes[:4]:
                    seeds.append(node)
                    self._add(node, "anchor", ContextEvidence("requested_symbol" if anchor.symbol else "requested_path", "requested"), 0)
                if len(nodes) > 4:
                    self._limitations.add("anchor_symbol_match_limit_reached")

            # retain initial lexical candidates without spending the semantic allowance on every match
            lexical = self.sources.index.search(query, relative_path=self.scope, limit=12)
            for match in lexical.matches:
                self._excerpt(
                    match.path, terms, ContextFileRoles.classify(match.path), ContextEvidence("query_word_overlap", "lexical"), 70
                )
            if not seeds:
                for match in lexical.matches[:2]:
                    if match.lines:
                        node = self.semantics.at_line(match.path, match.lines[0][0])
                        if node is not None:
                            seeds.append(node)
                            self._add(node, "code", ContextEvidence("symbol_containing_query_match", "language_server"), 30)

            # traverse at most two semantic hops; static references are not runtime call guarantees
            expanded_terms = set(terms)
            pending = deque((seed, 0) for seed in seeds[:4])
            visited = set()
            while pending and len(visited) < 6:
                CancellationToken.check_current()
                node, depth = pending.popleft()
                if node.reference in visited:
                    continue
                visited.add(node.reference)
                expanded_terms.update(LocalSourceIndex.terms(node.reference.symbol))
                for edge in self.semantics.references(node):
                    evidence = ContextEvidence(edge.kind, "language_server", edge.origin, edge.site)
                    role = "test" if ContextFileRoles.classify(edge.target.reference.path) == "test" else "caller"
                    self._add(edge.target, role, evidence, 20 if role == "test" else 50)
                if depth < 2:
                    for edge in self.semantics.dependencies(node):
                        evidence = ContextEvidence(edge.kind, "language_server", edge.origin, edge.site)
                        self._add(edge.target, "dependency", evidence, 25 + depth)
                        expanded_terms.update(LocalSourceIndex.terms(edge.target.reference.symbol))
                        if self._in_scope(edge.target.reference.path):
                            pending.append((edge.target, depth + 1))
            if pending:
                self._limitations.add("semantic_traversal_limit_reached")

            # use captured index metadata to find supporting roles that may be absent from the top code matches
            for role in ("test", "documentation", "configuration"):
                ranked = []
                for path, entry in self.sources.observation.files.items():
                    if self._in_scope(path) and entry.text_status == "indexed" and ContextFileRoles.classify(path) == role:
                        score = len(entry.terms & expanded_terms)
                        if score:
                            ranked.append((-score, path))
                for _, path in sorted(ranked)[:4]:
                    self._excerpt(path, frozenset(expanded_terms), role, ContextEvidence("related_identifier_overlap", "heuristic"), 45)
        except ContextLimitReached:
            self._limitations.add("context_source_file_limit_reached")
        self._limitations.update(self.semantics.limitations())
        if self._pool.limited:
            self._limitations.add("candidate_limit_reached")
        return self._pool.ordered()

    def limitations(self) -> tuple[str, ...]:
        return tuple(sorted(self._limitations))
