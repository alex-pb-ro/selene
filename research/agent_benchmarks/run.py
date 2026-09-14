"""Prepare controlled agent trials and validate the authored task/verifier package.

This program starts no agent and accepts no arbitrary candidate for native execution.
Its self-test executes only the trusted baselines, reference repairs and authored mutants.
"""

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

from cases import SourceFile, TaskCatalog, TaskSpec


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


class Workspace:
    """Materialize only task-visible data and account for application-file changes."""

    _EXCLUDED = frozenset({".git", ".selene", ".build", "__pycache__", ".pytest_cache"})
    _RULES = (
        "Keep task data in this workspace and the connected client. Do not contact external services, install dependencies, "
        "or read outside the task workspace. Use pre-provisioned tools. Preserve unrelated files. "
        "Build output belongs in .build/. These instructions are identical in every evaluation condition.\n"
    )

    @classmethod
    def create(cls, root: Path, task: TaskSpec) -> dict[str, str]:
        root.mkdir(parents=True, exist_ok=False)
        cls.write(root, task.visible_files + (SourceFile("TASK.md", task.prompt + "\n"), SourceFile("AGENTS.md", cls._RULES)))
        return cls.snapshot(root)

    @staticmethod
    def write(root: Path, files: tuple[SourceFile, ...]) -> None:
        for source in files:
            path = root / source.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source.content, encoding="utf-8", newline="")

    @classmethod
    def snapshot(cls, root: Path) -> dict[str, str]:
        result = {}
        for directory, folders, files in os.walk(root, followlinks=False):
            folders[:] = sorted(name for name in folders if name not in cls._EXCLUDED)
            for name in folders + sorted(files):
                path = Path(directory) / name
                if path.is_symlink():
                    raise ValueError("A task snapshot cannot follow candidate symlinks")
            for name in sorted(files):
                path = Path(directory) / name
                if not path.is_file():
                    raise ValueError("A task snapshot requires regular files")
                result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    @classmethod
    def changes(cls, root: Path, before: dict[str, str], task: TaskSpec) -> tuple[tuple[str, ...], tuple[str, ...]]:
        after = cls.snapshot(root)
        changed = tuple(sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path)))
        unintended = tuple(
            path
            for path in changed
            if path in task.protected_paths
            or not any(path.startswith(prefix) if prefix.endswith("/") else path == prefix for prefix in task.editable_prefixes)
        )
        return changed, unintended

    @classmethod
    def copy_for_verification(cls, source: Path, destination: Path) -> None:
        cls.snapshot(source)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*cls._EXCLUDED))


class TrustedFixtureVerifier:
    """Run independent checks after copying a trusted authored fixture into a controller directory.

    Real agent submissions require an equivalent isolated verifier with network/filesystem
    boundaries. Keeping graders in a sibling directory is not access control by itself.
    """

    def __init__(self, compiler: Path):
        self._compiler = compiler.resolve(strict=True)
        self._node = shutil.which("node")
        if self._node is None:
            raise ValueError("A pre-provisioned Node executable is required")

    @staticmethod
    def _environment(home: Path, workspace: Path) -> dict[str, str]:
        home.mkdir(exist_ok=True)
        return {
            "PATH": os.environ["PATH"],
            "SELENE_HOME": str(home),
            "TMPDIR": str(home),
            "PYTHONPATH": str(workspace),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "UV_OFFLINE": "1",
            "PYTHONIOENCODING": "utf-8",
        }

    def _python(self, controller: Path, task: TaskSpec, environment: dict[str, str]) -> tuple[CheckResult, ...]:
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

    def _typescript(self, controller: Path, task: TaskSpec, environment: dict[str, str]) -> tuple[CheckResult, ...]:
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

    def verify(self, workspace: Path, before: dict[str, str], task: TaskSpec) -> Verification:
        started = time.perf_counter()
        changed, unintended = Workspace.changes(workspace, before, task)
        with tempfile.TemporaryDirectory(prefix="selene-task-controller-") as temporary:
            controller = Path(temporary)
            candidate = controller / "workspace"
            Workspace.copy_for_verification(workspace, candidate)
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
        checks += missing
        passed = all(check.passed for check in checks) and not unintended
        return Verification(passed, checks, changed, unintended, round((time.perf_counter() - started) * 1000, 3))


class BenchmarkPreparation:
    """Prepare matched trials; starting agents and choosing providers are external, authorized actions."""

    _ARMS = {
        "native": None,
        "prior_selene": "5dc6cbd3ce9d59799774f2a22fe97c846d555196",
        "proposed_selene": "23f84eac01b99ac8ee87b9d91f6f873c11e4a260",
    }

    @staticmethod
    def self_test(compiler: Path) -> dict:
        verifier = TrustedFixtureVerifier(compiler)
        observations = []
        for task in TaskCatalog.all():
            for variant in ("baseline", "reference", "regression_mutant", "unrelated_edit"):
                with tempfile.TemporaryDirectory(prefix="selene-task-package-") as temporary:
                    workspace = Path(temporary) / "workspace"
                    before = Workspace.create(workspace, task)
                    if variant != "baseline":
                        Workspace.write(workspace, task.reference_repair)
                    if variant == "regression_mutant":
                        Workspace.write(workspace, (task.regression_mutant,))
                    if variant == "unrelated_edit":
                        path = workspace / task.protected_paths[0]
                        prefix = "//" if path.suffix == ".ts" else "#"
                        path.write_text(path.read_text() + f"\n{prefix} unrelated edit\n")
                    result = verifier.verify(workspace, before, task)
                    assert result.automated_checks_passed == (variant == "reference"), (task.identifier, variant, result)
                    if variant == "unrelated_edit":
                        assert task.protected_paths[0] in result.unintended_paths
                        assert all(check.passed for check in result.checks)
                    elif variant == "regression_mutant":
                        assert any(not check.passed for check in result.checks)
                    observations.append({"task": task.identifier, "variant": variant, **asdict(result)})
                    print(task.identifier, variant, "PASS" if result.automated_checks_passed else "REJECTED", flush=True)
        sources = (Path(__file__), Path(__file__).with_name("cases.py"))
        return {
            "synthetic_only": True,
            "agents_started": 0,
            "model_calls": 0,
            "uploaded_data": False,
            "meaning": "Trusted task-package self-test, not measured agent task success or an adversarial grader attestation.",
            "observations": observations,
            "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        }

    @classmethod
    def prepare(cls, output: Path, repeats: int, seed: int) -> dict:
        if not 1 <= repeats <= 20:
            raise ValueError("Use one to twenty planned repetitions")
        output.mkdir(parents=True, exist_ok=False)
        trials = []
        ordering = random.Random(seed)
        for task in TaskCatalog.all():
            for repetition in range(repeats):
                arms = list(cls._ARMS)
                ordering.shuffle(arms)
                paired_hashes = []
                for arm in arms:
                    identifier = f"{task.identifier}-{repetition:02}-{arm}"
                    root = output / "workspaces" / identifier
                    hashes = Workspace.create(root, task)
                    paired_hashes.append(hashes)
                    trials.append(
                        {
                            "id": identifier,
                            "task": task.identifier,
                            "repetition": repetition,
                            "arm": arm,
                            "server_revision": cls._ARMS[arm],
                            "workspace": str(root.resolve()),
                            "source_sha256": hashes,
                            "status": "not_started",
                            "agent_result": None,
                        }
                    )
                assert all(value == paired_hashes[0] for value in paired_hashes)
        manifest = {
            "schema_version": 1,
            "seed": seed,
            "agents_started": 0,
            "fixed_client_configuration": None,
            "scope_isolation_verified": None,
            "proposed_additional_tools": [
                "search_index",
                "find_context",
                "continue_context",
                "read_context_items",
                "analyze_change",
                "prepare_change",
                "apply_change",
                "recover_change",
                "check_memory",
                "review_memory",
            ],
            "trials": trials,
            "required_before_run": [
                "explicit authorization for fresh agent sessions and the approved client/provider",
                "one fixed model version, reasoning budget, client version and network policy",
                "agent native tools and MCP tools restricted to the task workspace, excluding controller source and graders",
                "separate isolated post-run verifier for agent-authored code; stop the agent before injecting checks",
                "provider-reported token counts or explicit unavailable values, timeouts/failures retained, human review of all prompt requirements",
            ],
            "paired_agent_results": None,
        }
        (output / "trial-plan.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return {"trial_plan": str((output / "trial-plan.json").resolve()), "trials_prepared": len(trials), "agents_started": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    self_test = commands.add_parser("self-test")
    self_test.add_argument("--typescript-compiler", type=Path, required=True)
    self_test.add_argument("--output", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--output-directory", type=Path, required=True)
    prepare.add_argument("--repeats", type=int, default=2)
    prepare.add_argument("--seed", type=int, default=20260914)
    arguments = parser.parse_args()
    if arguments.command == "self-test":
        result = BenchmarkPreparation.self_test(arguments.typescript_compiler)
        arguments.output.write_text(json.dumps(result, indent=2) + "\n")
    else:
        print(json.dumps(BenchmarkPreparation.prepare(arguments.output_directory, arguments.repeats, arguments.seed), indent=2))
