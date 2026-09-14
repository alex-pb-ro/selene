"""Run a sealed submission only after the inherited Linux network boundary is active."""

import base64
import hashlib
import json
import runpy
import site
import sys
from dataclasses import asdict
from pathlib import Path, PurePosixPath

# install the boundary before dependency hooks or candidate imports
boundary = runpy.run_path("/opt/selene/src/selene/isolation/linux_network.py")["LinuxNetworkBoundary"]
boundary.enter()
site.main()
sys.path.insert(0, "/opt/benchmark/dependencies")
sys.path.insert(0, "/opt/benchmark")

from checks import CheckSpec, FunctionalChecker


def main() -> None:
    payload = json.loads(Path("/submission/input.json").read_text())
    workspace = Path("/tmp/candidate")
    workspace.mkdir()

    # reconstruct regular files from controller-owned bytes, never archive paths or symlinks
    total = 0
    files = payload["files"]
    if len(files) > 512:
        raise ValueError("Too many submission files")
    for item in files:
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or not relative.parts or any(part in {".", ".."} for part in relative.parts):
            raise ValueError("Invalid submission path")
        data = base64.b64decode(item["content"], validate=True)
        total += len(data)
        if len(data) > 2 * 1024 * 1024 or total > 8 * 1024 * 1024:
            raise ValueError("Submission size limit exceeded")
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Submission digest mismatch")
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)

    # only this task's checks enter the verifier; references and other tasks remain outside
    spec = CheckSpec(payload["language"], payload["check_source"], tuple(payload["expected_checks"]))
    checker = FunctionalChecker(Path("/opt/benchmark/typescript/bin/tsc"), Path("/opt/benchmark/dependencies"))
    checks = checker.run(workspace, spec)
    result = {
        "submission_sha256": hashlib.sha256(Path("/submission/input.json").read_bytes()).hexdigest(),
        "checks": [asdict(check) for check in checks],
        "all_checks_passed": bool(checks) and all(check.passed for check in checks),
    }
    print("SELENE_VERIFICATION:" + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
