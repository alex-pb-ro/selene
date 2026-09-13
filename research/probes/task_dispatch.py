"""Measure warm task dispatch and MCP round trips without changing the original baseline."""

import asyncio
import hashlib
import json
import platform
import time
from pathlib import Path

from optimization_baseline import OptimizationBaseline


def main() -> None:
    probe = OptimizationBaseline()
    from selene.task_executor import TaskExecutor

    executor = TaskExecutor("dispatch-benchmark")
    samples = []
    for _ in range(30):
        start = time.perf_counter()
        assert executor.execute_task(lambda: 42, logged=False) == 42
        samples.append(time.perf_counter() - start)
    probe.results["sequential_noop_dispatch"] = probe.summarize(samples)
    asyncio.run(probe.mcp())
    source = Path("src/selene/task_executor.py")
    probe.results["method"] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "model_calls": 0,
        "scope": "Single-machine synthetic microbenchmark; MCP over stdio; no language servers or model inference.",
    }
    output = probe.root / "research/task-dispatch-results.json"
    output.write_text(json.dumps(probe.results, indent=2) + "\n")
    print(output.read_text())


if __name__ == "__main__":
    main()
