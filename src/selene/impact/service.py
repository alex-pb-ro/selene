"""Read-only impact reports for proposed text changes, bound to current source versions."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from selene.changes.model import MaterializedFileChange, ProposedFileChange
from selene.changes.resolver import ChangeResolver
from selene.context.semantic import LanguageServerContextProvider
from selene.context.sources import ContextSources
from selene.impact.adapters import ImpactAdapters
from selene.impact.graph import ImpactGraph
from selene.impact.model import ChangedFileSummary, ChangedSymbol, ImpactFinding, ImpactUncertainty
from selene.util.cancellation import CancellationToken
from selene.util.json_budget import JsonBudget

if TYPE_CHECKING:
    from selene.project import Project


@dataclass(frozen=True)
class TestRecommendation:
    path: str
    symbols: tuple[str, ...]
    sha256: str
    basis: str
    evidence: str
    depth: int


class ImpactReport:
    """Render bounded evidence without suggesting complete runtime or regression coverage."""

    @staticmethod
    def _tests(findings: list[ImpactFinding]) -> list[TestRecommendation]:
        selected: dict[str, list[ImpactFinding]] = {}
        for finding in findings:
            if finding.role != "test":
                continue
            source = finding.target
            matches = selected.setdefault(source.path, [])
            if not matches or finding.evidence == matches[0].evidence:
                matches.append(finding)
        return [
            TestRecommendation(
                path,
                tuple(sorted({item.target.symbol for item in matches if item.target.symbol})),
                matches[0].target.sha256,
                matches[0].relationship,
                matches[0].evidence,
                min(item.depth for item in matches),
            )
            for path, matches in selected.items()
        ]

    @classmethod
    def render(
        cls,
        changes: tuple[MaterializedFileChange, ...],
        graph: ImpactGraph,
        adapters: ImpactAdapters,
        sources: ContextSources,
        *,
        max_chars: int,
    ) -> str:
        if not 4096 <= max_chars <= 100000:
            raise ValueError("Impact output allowances must be between 4096 and 100000 JSON characters")
        # retain test and implementation evidence before approximate name matches
        findings = list(dict.fromkeys(graph.findings + adapters.findings))
        findings.sort(
            key=lambda item: (
                item.evidence == "heuristic",
                item.role != "test",
                item.role != "implementation",
                item.depth,
                item.target.path,
                item.target.start_line,
            )
        )
        uncertainties = [
            ImpactUncertainty(
                "static_relationships_do_not_prove_runtime_impact",
                "Review dynamic dispatch, reflection, dependency injection, generated code and runtime configuration.",
            ),
            ImpactUncertainty(
                "proposed_code_has_not_been_typechecked_or_executed",
                "Apply the reviewed change and run focused tests plus the project's independent broader regression gate.",
            ),
            ImpactUncertainty(
                "test_roles_are_filename_heuristics_not_runtime_coverage",
                "Check fixture setup and test discovery in the project's actual runner.",
            ),
            *graph.uncertainties,
            *adapters.uncertainties,
            *(
                ImpactUncertainty(reason, "Inspect the affected backend or narrow the analysis request.")
                for reason in graph.semantics.limitations()
            ),
        ]
        uncertainties = list(dict.fromkeys(uncertainties))
        changed_symbols: list[ChangedSymbol] = list(dict.fromkeys(graph.changed_symbols))
        available_findings = len(findings)
        available_uncertainties = len(uncertainties)
        available_symbols = len(changed_symbols)
        payload = {
            "status": "partial",
            "analysis_basis": "current_project_source_with_unapplied_proposed_changes",
            "generation": sources.observation.status.generation,
            "index_observed_at": sources.observation.status.observed_at,
            "index_mode": sources.observation.status.watcher,
            "semantic_operations": graph.semantics.calls_used(),
            "coordinates": "changed ranges use 0-based half-open lines; source references use 1-based inclusive lines; site columns use 0-based UTF-16",
            "changes": tuple(
                ChangedFileSummary(change.path, change.kind, change.expected_sha256, change.proposed_sha256, change.ranges)
                for change in changes
            ),
            "source_file_count": len(sources.versions()),
        }
        while True:
            CancellationToken.check_current()
            payload.update(
                changed_symbols=changed_symbols,
                language_server_relationships=[finding for finding in findings if finding.evidence == "language_server"],
                declared_relationships=[finding for finding in findings if finding.evidence == "declared_mapping"],
                heuristic_candidates=[finding for finding in findings if finding.evidence == "heuristic"],
                recommended_tests=cls._tests(findings),
                uncertainties=uncertainties,
                omitted_findings=available_findings - len(findings),
                omitted_uncertainties=available_uncertainties - len(uncertainties),
                omitted_changed_symbols=available_symbols - len(changed_symbols),
            )
            result = JsonBudget.serialize(payload, max_chars)
            if len(result) <= max_chars:
                return result
            if findings:
                findings.pop()
            elif len(uncertainties) > 2:
                uncertainties.pop()
            elif changed_symbols:
                changed_symbols.pop()
            else:
                raise ValueError("Changed-file metadata exceeds the output allowance; use fewer changed files or a larger budget")


class ChangeImpactAnalyzer:
    """Analyze one unapplied proposal without retaining bodies or invoking build/test commands."""

    def __init__(self, project: "Project"):
        self._project = project

    def analyze(
        self, *, diff: str = "", changes: tuple[ProposedFileChange, ...] = (), scope: str = "", max_chars: int = 20000, max_depth: int = 2
    ) -> str:
        if not 1 <= max_depth <= 4:
            raise ValueError("Impact traversal depth must be between one and four")
        self._project.ls_sync_file_system_changes()
        index = self._project.get_local_index()
        sources = ContextSources(index, index.refresh(), self._project.project_config.encoding, max_files=64)
        resolver = ChangeResolver(self._project, sources)
        materialized = resolver.resolve(diff=diff, changes=changes)
        semantics = LanguageServerContextProvider(self._project, sources, max_calls=96, seconds=20)
        graph = ImpactGraph(sources, semantics, scope, max_depth=max_depth)
        graph.analyze(materialized)
        adapters = ImpactAdapters(sources, scope)
        adapters.analyze(materialized, tuple(graph.changed_symbols))
        resolver.validate(materialized)
        result = ImpactReport.render(materialized, graph, adapters, sources, max_chars=max_chars)
        resolver.validate(materialized)
        return result
