"""Measure content-based source observation without changing the historical baseline."""

import hashlib
import json
import platform

from optimization_baseline import OptimizationBaseline


class FreshnessProbe:
    def run(self):
        baseline = OptimizationBaseline()
        baseline.freshness()
        files = [
            "src/selene/file_change_notifier.py",
            "src/selene/util/file_snapshot.py",
            "src/selene/project.py",
            "src/solidlsp/ls.py",
            "src/solidlsp/ls_utils.py",
        ]
        baseline.results["method"] = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "synthetic_only": True,
            "model_calls": 0,
            "language_servers": 0,
            "scope": "Same freshness workload as optimization_baseline.py; ten warm sequential full scans at each size.",
            "caveats": "Single-machine microbenchmark of discovery plus file hashing, not language-server indexing latency. "
            "This correctness change does not implement incremental indexing. File metadata is checked around each read; "
            "the project is not observed atomically. No packet capture was performed.",
            "source_sha256": {p: hashlib.sha256((baseline.root / p).read_bytes()).hexdigest() for p in files},
        }
        output = baseline.root / "research/freshness-results.json"
        output.write_text(json.dumps(baseline.results, indent=2) + "\n")
        print(output.read_text())


if __name__ == "__main__":
    FreshnessProbe().run()
