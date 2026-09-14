"""Controller-owned functional checks shared by trusted fixtures and isolated submissions."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class CheckSpec:
    language: Literal["python", "typescript"]
    check_source: str
    expected_checks: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class Verification:
    automated_checks_passed: bool
    checks: tuple[CheckResult, ...]
    changed_paths: tuple[str, ...]
    unintended_paths: tuple[str, ...]
    elapsed_ms: float
    human_review_required: bool = True


class FunctionalChecker:
    """Execute independent Python/TypeScript checks without selecting tasks or providers."""

    def __init__(self, compiler: Path, dependencies: Path | None = None):
        self._compiler = compiler.resolve(strict=True)
        self._dependencies = dependencies
        node = shutil.which("node")
        if node is None:
            raise ValueError("A pre-provisioned Node executable is required")
        self._node = node

    def _environment(self, home: Path, workspace: Path) -> dict[str, str]:
        home.mkdir(exist_ok=True)
        return {
            "PATH": os.environ["PATH"],
            "SELENE_HOME": str(home),
            "TMPDIR": str(home),
            "PYTHONPATH": os.pathsep.join(str(path) for path in (workspace, self._dependencies) if path is not None),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "UV_OFFLINE": "1",
            "PYTHONIOENCODING": "utf-8",
        }

    def _python(self, controller: Path, task: CheckSpec, environment: dict[str, str]) -> tuple[CheckResult, ...]:
        checks = controller / "test_independent_checks.py"
        checks.write_text(task.check_source)
        xml = controller / "checks.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(checks), "-q", "-p", "no:cacheprovider", "--junitxml", str(xml)],
            check=False,
            cwd=controller,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode not in {0, 1} or not xml.is_file():
            return (CheckResult("verifier_execution", False, (result.stdout + result.stderr)[-3000:]),)
        observed = []
        for case in ET.parse(xml).findall(".//testcase"):
            failure = next((child for child in case if child.tag in {"failure", "error", "skipped"}), None)
            observed.append(
                CheckResult(case.attrib["name"], failure is None, "" if failure is None else failure.attrib.get("message", "")[:1000])
            )
        return tuple(observed)

    def _typescript(self, controller: Path, task: CheckSpec, environment: dict[str, str]) -> tuple[CheckResult, ...]:
        checks = controller / "checks.ts"
        checks.write_text(task.check_source)
        workspace = controller / "workspace"
        files = [str(path) for path in sorted(workspace.rglob("*.ts"))]
        compile_result = subprocess.run(
            [
                str(self._compiler),
                "--strict",
                "--target",
                "ES2020",
                "--module",
                "commonjs",
                "--skipLibCheck",
                "--outDir",
                str(controller / "compiled"),
                "--rootDir",
                str(controller),
                str(checks),
                *files,
            ],
            check=False,
            cwd=controller,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if compile_result.returncode != 0:
            return (CheckResult("public_types_and_compilation", False, (compile_result.stdout + compile_result.stderr)[-3000:]),)
        result = subprocess.run(
            [self._node, str(controller / "compiled" / "checks.js")],
            check=False,
            cwd=controller,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        rows = [line.removeprefix("SELENE_TASK_CHECKS:") for line in result.stdout.splitlines() if line.startswith("SELENE_TASK_CHECKS:")]
        if result.returncode != 0 or len(rows) != 1:
            return (CheckResult("verifier_execution", False, (result.stdout + result.stderr)[-3000:]),)
        return tuple(CheckResult(**value) for value in json.loads(rows[0]))

    def run(self, workspace: Path, task: CheckSpec) -> tuple[CheckResult, ...]:
        """Run declared checks against a copied candidate; the caller owns OS confinement."""
        with tempfile.TemporaryDirectory(prefix="selene-task-controller-") as temporary:
            controller = Path(temporary)
            candidate = controller / "workspace"
            shutil.copytree(workspace, candidate, symlinks=True)
            environment = self._environment(controller / "home", candidate)
            try:
                checks = (
                    self._python(controller, task, environment)
                    if task.language == "python"
                    else self._typescript(controller, task, environment)
                )
            except subprocess.TimeoutExpired:
                checks = (CheckResult("verifier_timeout", False, "30-second verifier limit exceeded"),)
        names = {check.name for check in checks}
        missing = tuple(
            CheckResult(name, False, "Expected independent check did not execute") for name in task.expected_checks if name not in names
        )
        return checks + missing
