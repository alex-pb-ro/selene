"""Local schema, generation and heuristic evidence without executing project configuration."""

import json
import keyword
from pathlib import Path
from urllib.parse import unquote, urlsplit

from selene.changes.model import MaterializedFileChange
from selene.context.model import ContextLimitReached, SourceReference
from selene.context.sources import ContextFileRoles, ContextSources
from selene.impact.model import ChangedSymbol, ImpactFinding, ImpactUncertainty
from selene.indexing.local_index import LocalSourceIndex
from selene.util.cancellation import CancellationToken


class ChangeEvidence:
    """Describe a changed source range, explicitly distinguishing a proposed new file."""

    @staticmethod
    def origin(change: MaterializedFileChange) -> SourceReference:
        content = change.old_content if change.old_content is not None else change.new_content
        sha256 = change.expected_sha256 if change.old_content is not None else change.proposed_sha256
        assert content is not None and sha256 is not None
        lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        span = change.ranges[0]
        first = span.old_start if change.old_content is not None else span.new_start
        last = span.old_end if change.old_content is not None else span.new_end
        return SourceReference(change.path, sha256, min(first + 1, len(lines)), min(max(first + 1, last), len(lines)))


class ImpactAdapters:
    """Collect declared relationships and approximate candidates in separate categories."""

    _DYNAMIC = frozenset(
        {"getattr", "setattr", "globals", "locals", "reflect", "reflection", "inject", "injectable", "container", "provider"}
    )

    def __init__(self, sources: ContextSources, scope: str):
        self.sources = sources
        self.scope = sources.index.scope.normalize(scope)
        self.findings: list[ImpactFinding] = []
        self.uncertainties: list[ImpactUncertainty] = []

    def _in_scope(self, path: str) -> bool:
        return not self.scope or path == self.scope or path.startswith(self.scope + "/")

    def _local_path(self, path: str, base: str = "") -> str | None:
        return self.sources.resolve_indexed_path(self.sources.index.scope.root / base / path)

    @staticmethod
    def _changed_pointers(change: MaterializedFileChange) -> set[str]:
        if change.old_content is None or change.new_content is None:
            return {""}
        old, new = json.loads(change.old_content), json.loads(change.new_content)
        pending = [(old, new, "")]
        pointers = set()
        inspected = 0
        while pending:
            CancellationToken.check_current()
            before, after, path = pending.pop()
            inspected += 1
            if inspected > 4096 or len(pointers) > 256:
                raise ContextLimitReached("Schema comparison allowance exceeded")
            if isinstance(before, dict) and isinstance(after, dict):
                for key in before.keys() | after.keys():
                    child = path + "/" + key.replace("~", "~0").replace("/", "~1")
                    if key not in before or key not in after:
                        pointers.add(child)
                    else:
                        pending.append((before[key], after[key], child))
            elif isinstance(before, list) and isinstance(after, list):
                if len(before) != len(after):
                    pointers.add(path)
                else:
                    pending.extend(
                        (left, right, path + "/" + str(index)) for index, (left, right) in enumerate(zip(before, after, strict=False))
                    )
            elif isinstance(before, bool) != isinstance(after, bool) or before != after:
                pointers.add(path)
        return pointers

    @staticmethod
    def _references(value: object) -> tuple[tuple[str, str], ...]:
        pending = [(value, "")]
        references = []
        inspected = 0
        while pending:
            CancellationToken.check_current()
            current, pointer = pending.pop()
            inspected += 1
            if inspected > 4096:
                raise ContextLimitReached("Schema reference allowance exceeded")
            if isinstance(current, dict):
                for key, item in current.items():
                    if not isinstance(key, str):
                        continue
                    location = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
                    if key == "$ref" and isinstance(item, str):
                        references.append((location, item))
                    else:
                        pending.append((item, location))
            elif isinstance(current, list):
                pending.extend((item, pointer + "/" + str(index)) for index, item in enumerate(current))
        return tuple(references)

    def _schemas(self, changes: tuple[MaterializedFileChange, ...]) -> None:
        schema_changes = {}
        for change in changes:
            if change.path.endswith(".json"):
                try:
                    schema_changes[change.canonical_path] = (change, self._changed_pointers(change))
                except (ValueError, RecursionError):
                    self.uncertainties.append(
                        ImpactUncertainty(
                            "changed_json_could_not_be_compared",
                            "Validate the schema syntax and inspect its consumers.",
                            ChangeEvidence.origin(change),
                        )
                    )
        if not schema_changes:
            return
        for path, entry in self.sources.observation.files.items():
            if not path.endswith(".json") or entry.text_status != "indexed" or not self._in_scope(path):
                continue
            document = self.sources.read(path)
            try:
                references = self._references(json.loads("\n".join(document.lines)))
            except (ValueError, RecursionError):
                continue
            for pointer, raw in references:
                reference = urlsplit(raw)
                if reference.scheme or reference.netloc:
                    self.uncertainties.append(
                        ImpactUncertainty(
                            "remote_schema_reference_not_followed",
                            "Resolve this dependency through an explicitly approved local schema copy.",
                            document.reference(symbol=pointer),
                        )
                    )
                    continue
                target_path = path if not reference.path else self._local_path(unquote(reference.path), str(Path(path).parent))
                target = self.sources.observation.files.get(target_path or "")
                if target is None or target.canonical_path not in schema_changes:
                    continue
                change, changed = schema_changes[target.canonical_path]
                fragment = unquote(reference.fragment)
                if fragment and not fragment.startswith("/"):
                    self.uncertainties.append(
                        ImpactUncertainty(
                            "named_schema_anchor_unresolved",
                            "Inspect the named schema anchor manually.",
                            document.reference(symbol=pointer),
                        )
                    )
                    continue
                if any(value == fragment or value.startswith(fragment + "/") or fragment.startswith(value + "/") for value in changed):
                    site = document.reference(symbol=pointer)
                    self.findings.append(
                        ImpactFinding(
                            document.reference(),
                            "schema_consumer",
                            "local_json_schema_reference",
                            "declared_mapping",
                            ChangeEvidence.origin(change),
                            site,
                            1,
                        )
                    )

    def _generators(self, changes: tuple[MaterializedFileChange, ...]) -> None:
        manifest = "selene-impact.json"
        if not self.sources.contains(manifest):
            return
        document = self.sources.read(manifest)
        site = document.reference()
        try:
            configuration = json.loads("\n".join(document.lines))
            if not isinstance(configuration, dict) or configuration.get("version") != 1:
                raise ValueError("Expected generation mapping version 1")
            mappings = configuration.get("generators", [])
            if not isinstance(mappings, list) or len(mappings) > 32:
                raise ValueError("Invalid generator mappings")
            by_canonical = {change.canonical_path: change for change in changes}
            for mapping in mappings:
                if not isinstance(mapping, dict):
                    raise ValueError("Invalid generator mapping")
                inputs, outputs = mapping.get("inputs"), mapping.get("outputs")
                if any(
                    not isinstance(paths, list) or not 1 <= len(paths) <= 32 or not all(isinstance(path, str) for path in paths)
                    for paths in (inputs, outputs)
                ):
                    raise ValueError("Generator mappings need explicit input and output file lists")
                for raw_input in inputs:
                    path = self._local_path(raw_input)
                    entry = self.sources.observation.files.get(path or "")
                    if entry is None or entry.canonical_path not in by_canonical:
                        continue
                    change = by_canonical[entry.canonical_path]
                    for raw_output in outputs:
                        output = self._local_path(raw_output)
                        if output is None or not self._in_scope(output):
                            self.uncertainties.append(
                                ImpactUncertainty(
                                    "declared_generated_output_unavailable", "Check the declared mapping and the analysis scope.", site
                                )
                            )
                            continue
                        target = self.sources.read(output).reference()
                        self.findings.append(
                            ImpactFinding(
                                target,
                                "generated_output",
                                "declared_generation_input",
                                "declared_mapping",
                                ChangeEvidence.origin(change),
                                site,
                                1,
                            )
                        )
                    self.uncertainties.append(
                        ImpactUncertainty(
                            "generation_freshness_unverified",
                            "Regenerate and validate declared outputs using the project's approved workflow.",
                            site,
                        )
                    )
        except (ValueError, TypeError, RecursionError):
            self.uncertainties.append(
                ImpactUncertainty(
                    "invalid_generation_mapping", "Use selene-impact.json version 1 with explicit inputs and outputs arrays.", site
                )
            )

    @staticmethod
    def _terms(change: MaterializedFileChange, symbols: tuple[ChangedSymbol, ...]) -> set[str]:
        terms = set(LocalSourceIndex.terms(Path(change.path).stem))
        for symbol in symbols:
            if symbol.source.path == change.path:
                terms.update(LocalSourceIndex.terms(symbol.source.symbol))
        candidates = set()
        for content, proposed in ((change.old_content, False), (change.new_content, True)):
            if content is None:
                continue
            lines = content.splitlines()
            for span in change.ranges:
                start = span.new_start if proposed else span.old_start
                end = span.new_end if proposed else span.old_end
                candidates.update(LocalSourceIndex.terms("\n".join(lines[start : min(end, start + 32)])))
        candidates.difference_update(keyword.kwlist)
        candidates.difference_update({"self", "cls", "const", "let", "var", "true", "false", "null", "undefined", "int", "str", "bool"})
        terms.update(sorted(candidates - terms)[: max(0, 64 - len(terms))])
        return terms

    def _heuristics(self, changes: tuple[MaterializedFileChange, ...], symbols: tuple[ChangedSymbol, ...]) -> None:
        terms_by_change = [self._terms(change, symbols) for change in changes]
        ranked = []
        for path, entry in self.sources.observation.files.items():
            if entry.text_status != "indexed" or not self._in_scope(path):
                continue
            for index, terms in enumerate(terms_by_change):
                if not entry.terms & terms:
                    continue
                rank = len(entry.terms & terms)
                role = ContextFileRoles.classify(path)
                if role == "test":
                    rank += 5
                ranked.append((-rank, path, index))
        for _, path, index in sorted(ranked)[:16]:
            change, terms = changes[index], terms_by_change[index]
            document = self.sources.read(path)
            line = next((i for i, text in enumerate(document.lines, 1) if LocalSourceIndex.terms(text) & terms), 1)
            site = document.reference(line, line)
            role = ContextFileRoles.classify(path)
            self.findings.append(
                ImpactFinding(
                    document.reference(line, min(line + 12, len(document.lines))),
                    role,
                    "related_name_overlap",
                    "heuristic",
                    ChangeEvidence.origin(change),
                    site,
                    1,
                    origin_revision="proposed" if change.old_content is None else "current",
                )
            )
            if self.sources.observation.files[path].terms & self._DYNAMIC:
                self.uncertainties.append(
                    ImpactUncertainty(
                        "dynamic_lookup_or_dependency_injection_candidate",
                        "Inspect runtime wiring, reflection and fixture setup; a name match does not establish an execution path.",
                        site,
                    )
                )

    def analyze(self, changes: tuple[MaterializedFileChange, ...], symbols: tuple[ChangedSymbol, ...]) -> None:
        try:
            self._schemas(changes)
            self._generators(changes)
            self._heuristics(changes, symbols)
        except ContextLimitReached:
            self.uncertainties.append(
                ImpactUncertainty("adapter_resource_limit_reached", "Narrow the changed-file set or requested project scope.")
            )
