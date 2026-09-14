"""Measure static impact recall and missed regressions on independent synthetic tests."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from selene.changes.model import ProposedFileChange
from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.impact.service import ChangeImpactAnalyzer
from selene.project import Project
from solidlsp.ls_config import LanguageServerId


class ImpactEvaluation:
    """Compare selected tests against an independently fixed broader regression suite."""

    _FILES = {
        "policy.py": "def validate(value: int) -> bool:\n    return value >= 0\n",
        "client.py": "from policy import validate as decision\n\ndef submit(value: int) -> bool:\n    return decision(value)\n",
        "tests/test_direct.py": "from policy import validate\n\ndef test_direct():\n    assert validate(7)\n",
        "tests/test_primary.py": "from client import submit\n\ndef test_primary():\n    assert submit(7)\n",
        "tests/test_opaque.py": "def test_opaque():\n    fn = getattr(__import__('pol' + 'icy'), 'val' + 'idate')\n    assert fn(7) is True\n",
    }
    _PROPOSED = "def validate(value: int, strict: bool) -> bool:\n    return value >= 0\n"
    _EXPECTED_SITES = frozenset({("client.py", 4), ("tests/test_direct.py", 4), ("tests/test_primary.py", 4)})
    _EXPECTED_STATIC_TESTS = frozenset({"tests/test_direct.py", "tests/test_primary.py"})

    @staticmethod
    def _test_copy(parent: Path, original: Path, name: str, *, proposed: str | None, selection: list[str]) -> dict:
        copy = parent / name
        shutil.copytree(original, copy, ignore=shutil.ignore_patterns(".selene", "__pycache__", ".pytest_cache"))
        if proposed is not None:
            (copy / "policy.py").write_text(proposed)
        xml = parent / (name + ".xml")
        command = [sys.executable, "-m", "pytest", *selection, "-q", "--junitxml", str(xml)]
        result = subprocess.run(
            command,
            check=False,
            cwd=copy,
            env={**os.environ, "PYTHONPATH": str(copy), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode not in {0, 1} or not xml.is_file():
            raise RuntimeError("Synthetic regression runner failed: " + result.stdout + result.stderr)
        tests = ET.parse(xml).findall(".//testcase")
        return {
            "selection": selection,
            "test_count": len(tests),
            "failed_tests": sorted(
                test.attrib["name"] for test in tests if test.find("failure") is not None or test.find("error") is not None
            ),
            "exit_code": result.returncode,
        }

    def run(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="selene-impact-evaluation-") as temporary:
            base = Path(temporary)
            root = base / "source"
            root.mkdir()
            for path, content in self._FILES.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            baseline = self._test_copy(base, root, "baseline", proposed=None, selection=["tests"])
            assert not baseline["failed_tests"] and baseline["test_count"] == 3
            project = Project(
                project_root=str(root),
                project_config=ProjectConfig(project_name="impact-evaluation", language_servers=[LanguageServerId.PYTHON]),
                selene_config=SeleneConfig().with_headless_mode_overrides(),
            )
            try:
                project.create_language_server_manager()
                expected = hashlib.sha256((root / "policy.py").read_bytes()).hexdigest()
                start = time.perf_counter()
                raw = ChangeImpactAnalyzer(project).analyze(
                    changes=(ProposedFileChange("policy.py", expected, self._PROPOSED),), max_chars=30000
                )
                elapsed = time.perf_counter() - start
                report = json.loads(raw)
                assert hashlib.sha256((root / "policy.py").read_bytes()).hexdigest() == expected
            finally:
                project.shutdown()
            selected_paths = sorted({test["path"] for test in report["recommended_tests"]})
            observed_sites = {
                (finding["site"]["path"], finding["site"]["start_line"]) for finding in report["language_server_relationships"]
            }
            selected = self._test_copy(base, root, "selected", proposed=self._PROPOSED, selection=selected_paths)
            broader = self._test_copy(base, root, "broader", proposed=self._PROPOSED, selection=["tests"])
            missed = sorted(set(broader["failed_tests"]) - set(selected["failed_tests"]))
            assert set(selected_paths) >= self._EXPECTED_STATIC_TESTS
            assert observed_sites >= self._EXPECTED_SITES
            assert broader["test_count"] == 3 and len(broader["failed_tests"]) == 3
        repo = Path(__file__).resolve().parents[2]
        files = [
            *(repo / "src/selene/changes").glob("*.py"),
            *(repo / "src/selene/impact").glob("*.py"),
            *(repo / "src/selene/context").glob("*.py"),
            repo / "src/selene/util/json_budget.py",
            repo / "src/selene/project.py",
            repo / "src/selene/tools/impact_tools.py",
            Path(__file__),
        ]
        return {
            "method": {
                "fixture": "required-parameter API change, aliased caller, direct/indirect tests and one dynamically assembled reflective call",
                "model_calls": 0,
                "synthetic_only": True,
                "project_unchanged_by_analysis": True,
                "regression_gate": "all tests in the synthetic tests directory, chosen independently of the impact report",
                "source_sha256": {
                    path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)
                },
                "limitations": "One Python/Pyright fixture; no agent task-success or arbitrary-language completeness claim. The reflective case intentionally tests a static/lexical blind spot.",
            },
            "analysis": {
                "elapsed_ms": round(elapsed * 1000, 3),
                "json_characters": len(raw),
                "budget": report["budget"],
                "expected_static_sites": sorted(self._EXPECTED_SITES),
                "observed_sites": sorted(observed_sites),
                "known_static_site_recall": len(self._EXPECTED_SITES & observed_sites) / len(self._EXPECTED_SITES),
                "known_static_test_recall": len(self._EXPECTED_STATIC_TESTS & set(selected_paths)) / len(self._EXPECTED_STATIC_TESTS),
                "recommended_tests": report["recommended_tests"],
                "uncertainties": report["uncertainties"],
            },
            "baseline": baseline,
            "selected_after_proposal": selected,
            "broader_after_proposal": broader,
            "regressions_missed_by_selected_tests": missed,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = ImpactEvaluation().run()
    arguments.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
