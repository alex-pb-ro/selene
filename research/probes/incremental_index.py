"""Synthetic project indexing, notifier latency and I/O measurements; no model calls."""

import hashlib
import json
import logging
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

from selene.config.selene_config import ProjectConfig, SeleneConfig
from selene.file_change_notifier import LanguageServerFileChangeNotifier
from selene.project import Project
from solidlsp.ls_config import LanguageServerId


class EmptyManager:
    def iter_language_servers(self):
        return iter(())


class IncrementalIndexProbe:
    def __init__(self):
        self._observing = False
        self._events: dict[str, int] = {}
        sys.addaudithook(self._audit)

    def _audit(self, event, args):
        if self._observing and event in {"open", "os.scandir", "os.listdir"}:
            self._events[event] = self._events.get(event, 0) + 1

    def run(self):
        rows = []
        for count in [100, 1000, 10000]:
            with tempfile.TemporaryDirectory(prefix="selene-index-benchmark-", dir="/tmp") as directory:
                root = Path(directory).resolve()
                for number in range(count):
                    (root / f"module_{number}.py").write_text(f"def function_{number}():\n    return {number}\n")
                project = Project(
                    project_root=str(root), project_config=ProjectConfig(project_name="benchmark", language_servers=[LanguageServerId.PYTHON]),
                    selene_config=SeleneConfig().with_headless_mode_overrides(),
                )
                try:
                    start = time.perf_counter()
                    notifier = LanguageServerFileChangeNotifier(project, EmptyManager())
                    startup_ms = (time.perf_counter() - start) * 1000
                    samples = []
                    self._events.clear()
                    self._observing = True
                    try:
                        for _ in range(30):
                            start = time.perf_counter()
                            assert notifier.poll_and_notify() == 0
                            samples.append((time.perf_counter() - start) * 1000)
                    finally:
                        self._observing = False
                    before = (root / "module_0.py").stat()
                    (root / "module_0.py").write_text("def replacement():\n    return 9\n")
                    os.utime(root / "module_0.py", ns=(before.st_atime_ns, before.st_mtime_ns))
                    start = time.perf_counter()
                    assert notifier.poll_and_notify() == 1
                    changed_ms = (time.perf_counter() - start) * 1000
                    result = project.get_local_index().search("replacement")
                    assert [match.path for match in result.matches] == ["module_0.py"]
                    rows.append({
                        "files": count, "watcher": result.status.watcher, "startup_ms": round(startup_ms, 3),
                        "unchanged_median_ms": round(statistics.median(samples), 3),
                        "unchanged_p95_ms": round(sorted(samples)[28], 3),
                        "unchanged_io_events": self._events.copy(), "changed_file_ms": round(changed_ms, 3),
                    })
                finally:
                    project.shutdown()
        source_root = Path(__file__).resolve().parents[2]
        sources = list((source_root / "src/selene/indexing").glob("*.py")) + [source_root / "src/selene/file_change_notifier.py", source_root / "src/selene/project.py"]
        results = {
            "measurements": rows,
            "method": {
                "platform": platform.platform(), "python": platform.python_version(), "synthetic_only": True,
                "model_calls": 0, "language_servers": 0,
                "scope": "Real project/index/notifier, 30 unchanged observations; startup and one changed file measured once per size.",
                "limitations": "Single-machine microbenchmark. Directory creation and policy changes trigger full reconciliation. "
                    "Native events are advisory; the index periodically reconciles content and validates retrieved candidates. "
                    "Not a whole-project transaction, packet capture or language-server latency measurement.",
                "source_sha256": {str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
            },
        }
        output = source_root / "research/incremental-index-results.json"
        output.write_text(json.dumps(results, indent=2) + "\n")
        print(output.read_text())


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    IncrementalIndexProbe().run()
