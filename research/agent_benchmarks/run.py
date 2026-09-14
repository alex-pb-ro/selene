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
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from cases import SourceFile, TaskCatalog, TaskSpec
from checks import CheckSpec, FunctionalChecker, Verification


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
    def application_directories(cls, names: list[str]) -> list[str]:
        return sorted(name for name in names if name not in cls._EXCLUDED)

    @classmethod
    def snapshot(cls, root: Path) -> dict[str, str]:
        result = {}
        for directory, folders, files in os.walk(root, followlinks=False):
            folders[:] = cls.application_directories(folders)
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
        return cls.changed_paths(before, cls.snapshot(root), task)

    @staticmethod
    def changed_paths(before: dict[str, str], after: dict[str, str], task: TaskSpec) -> tuple[tuple[str, ...], tuple[str, ...]]:
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
    """Verify authored fixtures natively; arbitrary submissions require OS isolation."""

    def __init__(self, compiler: Path):
        self._checker = FunctionalChecker(compiler)

    def verify(self, workspace: Path, before: dict[str, str], task: TaskSpec) -> Verification:
        started = time.perf_counter()
        changed, unintended = Workspace.changes(workspace, before, task)
        with tempfile.TemporaryDirectory(prefix="selene-fixture-copy-") as temporary:
            candidate = Path(temporary) / "workspace"
            Workspace.copy_for_verification(workspace, candidate)
            checks = self._checker.run(candidate, CheckSpec(task.language, task.check_source, task.expected_checks))
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
        sources = tuple(Path(__file__).with_name(name) for name in ("run.py", "cases.py", "checks.py"))
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
