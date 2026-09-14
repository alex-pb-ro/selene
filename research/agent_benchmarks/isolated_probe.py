"""Exercise actual isolated verification using authored fixtures and local canaries only."""

import argparse
import base64
import hashlib
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from cases import SourceFile, TaskCatalog
from isolated import IsolatedSubmissionVerifier, SubmissionSnapshot
from run import Workspace


class IsolatedVerifierProbe:
    @staticmethod
    def run(verifier: IsolatedSubmissionVerifier) -> dict:
        observations = []
        for task in TaskCatalog.all():
            for variant in ("baseline", "reference", "regression_mutant", "unrelated_edit"):
                with tempfile.TemporaryDirectory(prefix="selene-isolated-fixture-") as temporary:
                    workspace = Path(temporary) / "workspace"
                    Workspace.create(workspace, task)
                    if variant != "baseline":
                        Workspace.write(workspace, task.reference_repair)
                    if variant == "regression_mutant":
                        Workspace.write(workspace, (task.regression_mutant,))
                    if variant == "unrelated_edit":
                        path = workspace / task.protected_paths[0]
                        prefix = "//" if path.suffix == ".ts" else "#"
                        path.write_text(path.read_text() + f"\n{prefix} unrelated edit\n")
                    result = verifier.verify(SubmissionSnapshot(workspace), task)
                    observations.append({"variant": variant, **result})
                    assert result["automated_checks_passed"] == (variant == "reference"), result
                    assert result["container_removed"], result
                    if variant == "unrelated_edit":
                        assert result["unintended_paths"] and all(check["passed"] for check in result["checks"])
                    print(task.identifier, variant, "EXPECTED", flush=True)

        task = TaskCatalog.all()[0]
        with tempfile.TemporaryDirectory(prefix="selene-verifier-canaries-") as temporary:
            outside = Path(temporary) / "outside.txt"
            outside.write_text("OUTSIDE_VERIFIER_SYNTHETIC_CANARY")
            workspace = Path(temporary) / "workspace"
            Workspace.create(workspace, task)
            Workspace.write(workspace, task.reference_repair)
            source = """import errno, os, socket, subprocess, sys
from pathlib import Path

def report():
    result = {}
    for domain in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.socket(domain, socket.SOCK_STREAM).close()
            result[str(domain)] = False
        except OSError as error:
            result[str(domain)] = error.errno == errno.EPERM
    for operation in ("connect", "bind"):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
            try:
                getattr(channel, operation)("/tmp/forbidden.sock")
                result[operation] = False
            except OSError as error:
                result[operation] = error.errno == errno.EPERM
    child = subprocess.run([sys.executable, "-c", "import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM)"], capture_output=True)
    result["inherited_child_denial"] = child.returncode != 0 and b"Operation not permitted" in child.stderr
    result["no_parent_secret"] = "SELENE_SYNTHETIC_VERIFIER_SECRET" not in os.environ
    result["outside_unreadable"] = not Path(OUTSIDE_PATH).exists()
    result["no_daemon_socket"] = not Path("/var/run/docker.sock").exists()
    result["no_reference_catalog"] = not Path("/opt/benchmark/cases.py").exists()
    result["nonroot"] = os.getuid() != 0
    result["no_new_privileges"] = "NoNewPrivs:\\t1" in Path("/proc/self/status").read_text()
    for path in ("/opt/benchmark/checks.py", "/submission/input.json"):
        try:
            with open(path, "ab") as stream:
                stream.write(b"changed")
            result[path] = False
        except OSError:
            result[path] = True
    left, right = socket.socketpair()
    try:
        left.send(b"x")
        result["private_socketpair_works"] = right.recv(1) == b"x"
    finally:
        left.close(); right.close()
    return result
""".replace("OUTSIDE_PATH", repr(str(outside)))
            Workspace.write(workspace, (SourceFile("shop/isolation_probe.py", source),))
            spec = replace(
                task,
                check_source=task.check_source
                + "\ndef test_verifier_boundary():\n    from shop.isolation_probe import report\n    result = report()\n    assert len(result) == 14 and all(result.values()), result\n",
                expected_checks=task.expected_checks + ("test_verifier_boundary",),
            )
            previous = os.environ.get("SELENE_SYNTHETIC_VERIFIER_SECRET")
            os.environ["SELENE_SYNTHETIC_VERIFIER_SECRET"] = "PARENT_ONLY_SYNTHETIC_CANARY"
            try:
                boundary = verifier.verify(SubmissionSnapshot(workspace), spec)
            finally:
                if previous is None:
                    del os.environ["SELENE_SYNTHETIC_VERIFIER_SECRET"]
                else:
                    os.environ["SELENE_SYNTHETIC_VERIFIER_SECRET"] = previous
            assert boundary["automated_checks_passed"], boundary
            assert outside.read_text() == "OUTSIDE_VERIFIER_SYNTHETIC_CANARY"
            print("boundary canaries EXPECTED", flush=True)

            # seal a reference, then change its original file before the container starts
            sealed = SubmissionSnapshot(workspace)
            (workspace / "shop/policy.py").write_text("def authorize(*args):\n    return False\n")
            immutable = verifier.verify(sealed, task)
            assert immutable["automated_checks_passed"], immutable
            assert (workspace / "shop/policy.py").read_text().endswith("return False\n")
            print("sealed bytes EXPECTED", flush=True)

            # require the outer deadline to remove a container containing a live child
            Workspace.write(workspace, task.reference_repair)
            with (workspace / "shop/policy.py").open("a") as stream:
                stream.write(
                    "\nimport subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\ntime.sleep(120)\n"
                )
            timeout = verifier.verify(SubmissionSnapshot(workspace), task, timeout=3)
            assert timeout["failure"] == "timeout" and timeout["container_removed"] and not timeout["automated_checks_passed"], timeout
            print("timeout and descendant removal EXPECTED", flush=True)

        rejected = {}
        with tempfile.TemporaryDirectory(prefix="selene-snapshot-contract-") as temporary:
            root = Path(temporary)
            for variant in ("symlink", "directory_symlink", "fifo", "hardlink", "oversized"):
                candidate = root / variant
                candidate.mkdir()
                target = candidate / "source.py"
                if variant == "symlink":
                    target.symlink_to("/etc/passwd")
                elif variant == "directory_symlink":
                    target.symlink_to(root, target_is_directory=True)
                elif variant == "fifo":
                    os.mkfifo(target)
                elif variant == "hardlink":
                    original = root / "original.py"
                    original.write_text("x = 1\n")
                    os.link(original, target)
                else:
                    target.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
                try:
                    SubmissionSnapshot(candidate)
                    rejected[variant] = False
                except (ValueError, OSError):
                    rejected[variant] = True
            assert all(rejected.values()), rejected
            candidate = root / "exact"
            candidate.mkdir()
            (candidate / "unicode.py").write_bytes('name = "\u03bb"\r\n'.encode())
            sealed = SubmissionSnapshot(candidate)
            exact = base64.b64decode(sealed.files[0].content) == (candidate / "unicode.py").read_bytes()
            assert exact

        names = (
            "isolated.py",
            "container_worker.py",
            "checks.py",
            "isolated_probe.py",
            "run.py",
            "cases.py",
            "Verifier.Dockerfile",
            "build_context.py",
        )
        return {
            "synthetic_only": True,
            "agents_started": 0,
            "model_calls": 0,
            "uploads": False,
            "observations": observations,
            "boundary_canaries": boundary,
            "sealed_snapshot": immutable,
            "timeout_cleanup": timeout,
            "snapshot_rejections": rejected,
            "unicode_crlf_bytes_preserved": exact,
            "agent_scope_verified": False,
            "adversarial_grader_attestation": False,
            "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names},
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-socket", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verifier = IsolatedSubmissionVerifier(args.docker_socket, args.image, args.staging)
    result = IsolatedVerifierProbe.run(verifier)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
