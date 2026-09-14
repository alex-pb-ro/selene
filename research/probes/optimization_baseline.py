"""Measure current scheduling, freshness and MCP overhead using synthetic data."""

import asyncio
import hashlib
import json
import logging
import math
import os
import platform
import statistics
import tempfile
import threading
import time
from pathlib import Path


class OptimizationBaseline:
    def __init__(self):
        self.root = Path(__file__).resolve().parents[2]
        self.base = Path(tempfile.mkdtemp(prefix="selene-optimization-"))
        os.environ["SELENE_HOME"] = str(self.base / "home")
        logging.disable(logging.CRITICAL)
        self.results = {}

    @staticmethod
    def summarize(samples):
        return {
            "n": len(samples),
            "median_ms": round(statistics.median(samples) * 1000, 3),
            "p95_ms": round(sorted(samples)[math.ceil(0.95 * len(samples)) - 1] * 1000, 3),
            "min_ms": round(min(samples) * 1000, 3),
            "max_ms": round(max(samples) * 1000, 3),
        }

    def scheduling(self):
        from selene.task_executor import TaskExecutor

        executor = TaskExecutor("research-idle")
        samples = []
        for _ in range(30):
            start = time.perf_counter()
            assert executor.execute_task(lambda: 42, logged=False) == 42
            samples.append(time.perf_counter() - start)
        self.results["sequential_noop_dispatch"] = self.summarize(samples)

        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_operation():
            started.set()
            release.wait(2)
            finished.set()

        executor = TaskExecutor("research-timeout")
        first = executor.issue_task(slow_operation, logged=False, timeout=0.025)
        assert started.wait(2)
        second = executor.issue_task(lambda: not finished.is_set(), logged=False)
        overlap = second.result(timeout=2)
        release.set()
        assert finished.wait(2)
        first.result(timeout=2)

        started.clear()
        release.clear()
        finished.clear()
        task = executor.issue_task(slow_operation, logged=False)
        assert started.wait(2)
        task.cancel()
        release.set()
        assert finished.wait(2)
        self.results["executor_safety"] = {
            "next_task_runs_while_timed_out_operation_is_active": overlap,
            "cancelled_future": task.future.cancelled(),
            "operation_side_effect_occurs_after_cancel": finished.is_set(),
            "scope": "Real executor; side effect is only setting an in-memory Event. No project edits.",
        }

    def freshness(self):
        from selene.config.selene_config import ProjectConfig, SeleneConfig
        from selene.ls_manager import LanguageServerFileChangeNotifier
        from selene.project import Project
        from solidlsp.ls_config import LanguageServerId

        class EmptyManager:
            def iter_language_servers(self):
                return iter(())

        rows = []
        for count in [100, 1000, 10000]:
            root = self.base / f"files-{count}"
            root.mkdir()
            for i in range(count):
                (root / f"module_{i:05}.py").write_text(f"def value_{i}():\n    return {i}\n")
            project = Project(
                project_root=str(root),
                project_config=ProjectConfig(project_name=f"synthetic-{count}", language_servers=[LanguageServerId.PYTHON]),
                selene_config=SeleneConfig().with_headless_mode_overrides(),
            )
            notifier = LanguageServerFileChangeNotifier(project, EmptyManager())
            samples = []
            for _ in range(10):
                start = time.perf_counter()
                assert notifier.poll_and_notify() == 0
                samples.append(time.perf_counter() - start)
            rows.append({"files": count, **self.summarize(samples)})
            if count == 100:
                target = root / "module_00000.py"
                before = target.read_bytes()
                timestamp = target.stat()
                target.write_text("def value_0():\n    return 9\n")
                os.utime(target, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
                preserved = notifier.poll_and_notify()
                target.write_text("def value_0():\n    return 8\n")
                os.utime(target, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns - 1_000_000_000))
                older = notifier.poll_and_notify()
                self.results["freshness_correctness"] = {
                    "content_changed": target.read_bytes() != before,
                    "events_after_preserving_mtime": preserved,
                    "events_after_decreasing_mtime": older,
                    "scope": "Real file-discovery/notifier code; no live language server. Its own watcher may independently detect changes.",
                }
        self.results["unchanged_project_poll"] = rows

    async def mcp(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        project = self.base / "mcp-project"
        (project / ".selene").mkdir(parents=True)
        (project / ".selene/project.yml").write_text("project_name: synthetic-benchmark\nlanguage_servers: []\n")
        rows = []
        for context in ["desktop-app", "ide", "codex"]:
            params = StdioServerParameters(
                command=str(self.root / ".venv/bin/selene"),
                args=[
                    "start-mcp-server",
                    "--project",
                    str(project),
                    "--context",
                    context,
                    "--enable-web-dashboard",
                    "false",
                    "--enable-gui-log-window",
                    "false",
                    "--log-level",
                    "ERROR",
                ],
                env={**os.environ, "SELENE_HOME": str(self.base / f"mcp-home-{context}")},
            )
            with (self.base / f"{context}-stderr.log").open("w") as stderr:
                start = time.perf_counter()
                async with stdio_client(params, errlog=stderr) as (read, write):
                    async with ClientSession(read, write) as session:
                        init = await session.initialize()
                        initialized = time.perf_counter() - start
                        tools = await session.list_tools()
                        schema = json.dumps([t.model_dump(exclude_none=True) for t in tools.tools], separators=(",", ":"))
                        samples = []
                        for _ in range(12):
                            start = time.perf_counter()
                            result = await session.call_tool("list_memories", {})
                            samples.append(time.perf_counter() - start)
                            assert not result.isError, result.model_dump()
                        rows.append(
                            {
                                "context": context,
                                "tool_count": len(tools.tools),
                                "serialized_tool_catalog_bytes": len(schema.encode()),
                                "initial_instructions_chars": len(init.instructions or ""),
                                "initialization_ms": round(initialized * 1000, 3),
                                "protocol": init.protocolVersion,
                                "list_memories_round_trip": self.summarize(samples),
                            }
                        )
        self.results["mcp_contexts"] = rows

    def run(self):
        self.scheduling()
        self.freshness()
        asyncio.run(self.mcp())
        files = ["src/selene/task_executor.py", "src/selene/ls_manager.py", "src/selene/project.py", "src/selene/mcp.py"]
        self.results["method"] = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "temporary_directory": str(self.base),
            "synthetic_only": True,
            "runtime_modified": False,
            "model_calls": 0,
            "network_scope": "No model or Internet calls configured; MCP over stdio; not a packet capture.",
            "caveats": "Single-machine microbenchmarks, sequential warm filesystem samples; startup measured once per context without language servers. Catalog bytes are not model tokens. No proposed optimization implemented.",
            "source_sha256": {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in files},
        }
        output = self.root / "research/optimization-baseline.json"
        output.write_text(json.dumps(self.results, indent=2) + "\n")
        print(json.dumps(self.results, indent=2))


if __name__ == "__main__":
    OptimizationBaseline().run()
