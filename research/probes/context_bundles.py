"""Synthetic, fixed-budget context retrieval evaluation without model calls."""

import argparse
import hashlib
import json
import platform
import tempfile
import time
from pathlib import Path

from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.context.bundles import ContextPageRenderer, ContextPlan
from selene.context.model import ContextAnchor, ContextCandidate, ContextEvidence
from selene.context.sources import ContextFileRoles, ContextSources
from selene.project import Project
from solidlsp.ls_config import LanguageServerId


class ContextEvaluation:
    """Compare first-page source coverage with an anchored lexical baseline."""

    _QUERY = "checkout payment"
    _BUDGET = 15000
    _SOURCES = {
        "checkout.py": "from policy import authorize as check_policy\nfrom models import Payment\n\ndef checkout(payment: Payment) -> bool:\n    return check_policy(payment)\n",
        "policy.py": "from models import Payment\n\ndef authorize(payment: Payment) -> bool:\n    return payment.amount < 100\n",
        "models.py": "from dataclasses import dataclass\n\n@dataclass\nclass Payment:\n    amount: int\n",
        "tests/test_checkout.py": "from checkout import checkout\nfrom models import Payment\n\ndef test_checkout():\n    assert checkout(Payment(50))\n",
        "docs/approval.md": "# Approval\nA payment must be approved before checkout.\n",
        "settings.toml": "payment_limit = 100\n",
        "unrelated.py": "def authorize(value):\n    return value\n",
    }
    _EXPECTED = frozenset(_SOURCES) - {"unrelated.py"}

    def _baseline(self, project: Project) -> str:
        index = project.get_local_index()
        matches = index.search(self._QUERY, limit=12)
        sources = ContextSources(index, index.refresh(), project.project_config.encoding)
        paths = list(dict.fromkeys(["checkout.py", *(match.path for match in matches.matches)]))
        candidates = []
        for path in paths:
            document = sources.read(path)
            reference = document.reference(1, min(13, len(document.lines)))
            candidates.append(
                ContextCandidate(
                    reference,
                    document.canonical_path,
                    (ContextFileRoles.classify(path),),
                    (ContextEvidence("query_word_overlap", "lexical"),),
                    50,
                )
            )
        plan = ContextPlan(
            "anchored-lexical-baseline",
            time.monotonic(),
            sources.observation.status.generation,
            tuple(candidates),
            sources.versions(),
            ("bounded_selection_not_exhaustive",),
            0,
        )
        return ContextPageRenderer.render(plan, sources, offset=0, max_chars=self._BUDGET, include_bodies=True)

    def _metrics(self, raw: str, elapsed: float) -> dict:
        page = json.loads(raw)
        items = page["items"]
        found = {item["source"]["path"] for item in items}
        duplicates = 0
        for index, item in enumerate(items):
            for other in items[:index]:
                a, b = item["source"], other["source"]
                if item["canonical_path"] == other["canonical_path"] and max(a["start_line"], b["start_line"]) <= min(
                    a["end_line"], b["end_line"]
                ):
                    duplicates += 1
        assert len(raw) == page["budget"]["used"] <= self._BUDGET
        return {
            "elapsed_ms": round(elapsed * 1000, 3),
            "json_characters": len(raw),
            "expected_paths": sorted(self._EXPECTED),
            "returned_paths": sorted(found),
            "expected_source_recall": len(found & self._EXPECTED) / len(self._EXPECTED),
            "overlapping_range_pairs": duplicates,
            "items": len(items),
            "semantic_operations": page["semantic_operations"],
            "limitations": page["limitations"],
            "has_continuation": page["continuation"] is not None,
        }

    def run(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="selene-context-evaluation-") as temporary:
            root = Path(temporary)
            for path, content in self._SOURCES.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            for number in range(40):
                (root / f"noise_{number:02}.py").write_text(
                    f"# Checkout payment examples, unrelated to approval.\ndef checkoutPaymentExample{number}():\n    return 'example'\n"
                )
            project = Project(
                project_root=str(root),
                project_config=ProjectConfig(project_name="context-evaluation", language_servers=[LanguageServerId.PYTHON]),
                selene_config=SeleneConfig().with_headless_mode_overrides(),
            )
            try:
                project.create_language_server_manager()
                project.get_local_index().refresh()
                start = time.perf_counter()
                baseline = self._baseline(project)
                baseline_metrics = self._metrics(baseline, time.perf_counter() - start)
                start = time.perf_counter()
                context = project.get_context_service().find(
                    self._QUERY, (ContextAnchor("checkout.py", "checkout"),), max_chars=self._BUDGET
                )
                context_metrics = self._metrics(context, time.perf_counter() - start)
            finally:
                project.shutdown()
        repo = Path(__file__).resolve().parents[2]
        sources = [
            *sorted((repo / "src/selene/context").glob("*.py")),
            repo / "src/selene/project.py",
            repo / "src/selene/tools/context_tools.py",
            Path(__file__),
        ]
        return {
            "method": {
                "fixture": "aliased payment policy, data type, test, docs and config with 40 similarly named distractors",
                "model_calls": 0,
                "budget_json_characters": self._BUDGET,
                "baseline": "explicit anchor plus top 12 local lexical matches, first 13 lines, same JSON page renderer",
                "measurement": "single first-page observation after language-server startup and index warmup",
                "platform": platform.platform(),
                "limitations": "One synthetic fixture; source-file recall is not symbol recall or agent task success. No paired model evaluation, grep, map or language-wide comparison.",
                "source_sha256": {path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
            },
            "anchored_lexical": baseline_metrics,
            "context_bundle": context_metrics,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = ContextEvaluation().run()
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
