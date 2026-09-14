"""Verify stopped benchmark submissions through an immutable local Docker image."""

import argparse
import base64
import hashlib
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from cases import TaskCatalog, TaskSpec
from run import Workspace


@dataclass(frozen=True)
class SubmissionFile:
    path: str
    content: str
    sha256: str


class SubmissionSnapshot:
    """Seal bounded regular-file bytes without importing or executing candidate code."""

    def __init__(self, root: Path):
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Candidate must be a directory")
        files = []
        total = 0
        for directory, folders, names, descriptor in os.fwalk(root, follow_symlinks=False):
            folders[:] = Workspace.application_directories(folders)
            for name in folders:
                if not stat.S_ISDIR(os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode):
                    raise ValueError("Candidate directories cannot be symlinks")
            for name in sorted(names):
                if len(files) >= 512:
                    raise ValueError("Candidate exceeds 512 files")
                handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                try:
                    before = os.fstat(handle)
                    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                        raise ValueError("Candidate files must be regular files without hardlink aliases")
                    if before.st_size > 2 * 1024 * 1024:
                        raise ValueError("Candidate file exceeds 2 MiB")
                    data = bytearray()
                    while chunk := os.read(handle, min(65536, 2 * 1024 * 1024 + 1 - len(data))):
                        data.extend(chunk)
                        if len(data) > 2 * 1024 * 1024:
                            raise ValueError("Candidate file grew beyond its size limit")
                    after = os.fstat(handle)
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise ValueError("Candidate changed while being sealed; stop its writer first")
                finally:
                    os.close(handle)
                total += len(data)
                if total > 8 * 1024 * 1024:
                    raise ValueError("Candidate exceeds 8 MiB")
                relative = (Path(directory) / name).relative_to(root).as_posix()
                files.append(SubmissionFile(relative, base64.b64encode(data).decode("ascii"), hashlib.sha256(data).hexdigest()))
        self.files = tuple(files)

    def changes(self, task: TaskSpec) -> tuple[list[str], list[str]]:
        with tempfile.TemporaryDirectory(prefix="selene-baseline-") as temporary:
            before = Workspace.create(Path(temporary) / "workspace", task)
        after = {item.path: item.sha256 for item in self.files}
        changed, unintended = Workspace.changed_paths(before, after, task)
        return list(changed), list(unintended)


@dataclass(frozen=True)
class MountSettings:
    destination: str
    writable: bool


@dataclass(frozen=True)
class ContainerSettings:
    network: str
    logging: str
    read_only_root: bool
    user: str
    mounts: tuple[MountSettings, ...]
    oom_killed: bool
    cap_drop: tuple[str, ...]
    security_options: tuple[str, ...]

    def is_isolated(self) -> bool:
        return (
            self.network == "none"
            and self.logging == "none"
            and self.read_only_root
            and self.user == "65534:65534"
            and self.mounts == (MountSettings("/submission/input.json", False),)
            and self.cap_drop == ("ALL",)
            and any(option.split("=")[0] == "no-new-privileges" for option in self.security_options)
        )


class IsolatedSubmissionVerifier:
    """Own local image validation, sealed input, bounded execution and container cleanup."""

    def __init__(self, docker_socket: Path, image: str, staging: Path):
        socket = docker_socket.resolve(strict=True)
        if not stat.S_ISSOCK(socket.stat().st_mode):
            raise ValueError("Use a local Docker Unix socket")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("Use an immutable local image ID")
        docker = shutil.which("docker")
        if docker is None:
            raise ValueError("A local Docker CLI is required")
        self._command = [docker, "--host", "unix://" + str(socket)]
        self._image = image
        self._staging = staging.resolve(strict=True)
        if not self._staging.is_dir() or any(character in str(self._staging) for character in (",", "\n", "\r")):
            raise ValueError("Use an existing daemon-shared staging directory without mount delimiters")

    def _docker(self, arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(self._command + arguments, env=environment, capture_output=True, text=True, timeout=15, check=False)

    @staticmethod
    def _collect(process: subprocess.Popen, timeout: float) -> tuple[str, str | None]:
        stream = process.stdout
        if stream is None:
            raise ValueError("Verifier collection requires a stdout pipe")
        deadline = time.monotonic() + timeout
        output = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return output.decode("utf-8", errors="replace"), "timeout"
                for key, _ in selector.select(min(remaining, 0.2)):
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(data)
                    if len(output) > 2 * 1024 * 1024:
                        return output[:4096].decode("utf-8", errors="replace"), "output_limit"
            try:
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return output.decode("utf-8", errors="replace"), "timeout"
        return output.decode("utf-8", errors="replace"), None

    def verify(self, snapshot: SubmissionSnapshot, task: TaskSpec, timeout: float = 90) -> dict:
        if not 1 <= timeout <= 120:
            raise ValueError("Verifier timeout must be between 1 and 120 seconds")
        changed, unintended = snapshot.changes(task)
        payload = {
            "files": [asdict(item) for item in snapshot.files],
            "language": task.language,
            "check_source": task.check_source,
            "expected_checks": task.expected_checks,
        }
        encoded = (json.dumps(payload, sort_keys=True) + "\n").encode()
        digest = hashlib.sha256(encoded).hexdigest()
        name = "selene-verify-" + uuid.uuid4().hex
        with (
            tempfile.TemporaryDirectory(prefix="verifier-client-") as configuration,
            tempfile.TemporaryDirectory(prefix="sealed-", dir=self._staging) as temporary,
        ):
            environment = {"PATH": os.environ["PATH"], "DOCKER_CONFIG": configuration}
            inspected = self._docker(["image", "inspect", self._image], environment)
            inspected.check_returncode()
            artifact = json.loads(inspected.stdout)[0]
            if artifact["Config"].get("Labels", {}).get("io.selene.benchmark.profile") != "submission-v1":
                raise ValueError("Image is not a benchmark verifier artifact")
            submission = Path(temporary)
            (submission / "input.json").write_bytes(encoded)
            (submission / "input.json").chmod(0o444)
            command = self._command + [
                "run",
                "--name=" + name,
                "--pull=never",
                "--network=none",
                "--log-driver=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--init",
                "--pids-limit=128",
                "--memory=1g",
                "--cpus=2",
                "--user=65534:65534",
                "--ipc=none",
                "--tmpfs=/tmp:rw,nosuid,nodev,size=256m,mode=1777",
                "--workdir=/tmp",
                "--mount",
                f"type=bind,src={submission / 'input.json'},dst=/submission/input.json,readonly,bind-recursive=disabled",
                "--entrypoint=/opt/selene/.venv/bin/python",
                self._image,
                "-I",
                "-S",
                "/opt/benchmark/container_worker.py",
            ]
            started = time.perf_counter()
            process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
            settings = None
            cleanup = False
            try:
                output, failure = self._collect(process, timeout)
                if failure:
                    process.kill()
                    process.wait(timeout=5)
                result = self._docker(["inspect", name], environment)
                if result.returncode == 0:
                    actual = json.loads(result.stdout)[0]
                    settings = ContainerSettings(
                        network=actual["HostConfig"]["NetworkMode"],
                        logging=actual["HostConfig"]["LogConfig"]["Type"],
                        read_only_root=actual["HostConfig"]["ReadonlyRootfs"],
                        user=actual["Config"]["User"],
                        mounts=tuple(MountSettings(mount["Destination"], mount["RW"]) for mount in actual["Mounts"]),
                        oom_killed=actual["State"]["OOMKilled"],
                        cap_drop=tuple(actual["HostConfig"]["CapDrop"]),
                        security_options=tuple(actual["HostConfig"]["SecurityOpt"]),
                    )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                removed = self._docker(["rm", "--force", name], environment)
                cleanup = removed.returncode == 0
                if process.stdout is not None:
                    process.stdout.close()
            records = [line.removeprefix("SELENE_VERIFICATION:") for line in output.splitlines() if line.startswith("SELENE_VERIFICATION:")]
            checks = []
            if not failure and process.returncode == 0 and len(records) == 1:
                try:
                    record = json.loads(records[0])
                    if record["submission_sha256"] != digest:
                        raise ValueError("Verifier returned another submission's digest")
                    checks = record["checks"]
                    if any(type(check["passed"]) is not bool for check in checks):
                        raise ValueError("Invalid check status")
                except (ValueError, KeyError, TypeError):
                    failure = "invalid_result"
            elif not failure:
                failure = "verifier_execution"
            present = {check["name"] for check in checks}
            if not set(task.expected_checks).issubset(present):
                failure = failure or "missing_checks"
            isolated = settings is not None and settings.is_isolated()
            passed = not failure and bool(checks) and all(check["passed"] for check in checks) and not unintended and isolated and cleanup
            return {
                "task": task.identifier,
                "image": self._image,
                "submission_sha256": digest,
                "automated_checks_passed": bool(passed),
                "checks": checks,
                "failure": failure,
                "changed_paths": changed,
                "unintended_paths": unintended,
                "container_settings": asdict(settings) if settings is not None else None,
                "container_removed": cleanup,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "human_review_required": True,
                "agent_scope_verified": False,
                "failure_output_tail": output[-3000:] if failure else None,
            }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--task", choices=[task.identifier for task in TaskCatalog.all()], required=True)
    parser.add_argument("--docker-socket", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verifier = IsolatedSubmissionVerifier(args.docker_socket, args.image, args.staging)
    result = verifier.verify(SubmissionSnapshot(args.candidate), TaskCatalog.get(args.task), args.timeout)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"automated_checks_passed": result["automated_checks_passed"], "failure": result["failure"]}))
