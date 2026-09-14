"""Exercise kernel-enforced network restrictions using only synthetic container data."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


class LinuxNetworkProbe:
    IMAGE = "python@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534"

    def __init__(self, socket_path: str):
        self.root = Path(__file__).resolve().parents[2]
        self.endpoint = "unix://" + str(Path(socket_path).resolve(strict=True))
        self.name = "selene-net-probe-" + uuid.uuid4().hex[:12]
        self.environment = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR")}

    def _docker(self, *args: str, source: str | None = None) -> str:
        result = subprocess.run(
            ["docker", "--host", self.endpoint, *args],
            input=source,
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError(f"Docker probe failed: {result.stderr}")
        return result.stdout

    def run(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="selene-probe-docker-") as docker_config:
            self.environment["DOCKER_CONFIG"] = docker_config
            self.environment["SELENE_SYNTHETIC_PARENT_SECRET"] = "parent-only-canary"
            self._docker("image", "inspect", self.IMAGE)
            self._docker("volume", "create", self.name)
            try:
                return self._exercise()
            finally:
                self._docker("rm", "--force", self.name)
                self._docker("volume", "rm", self.name)

    def _exercise(self) -> dict:
        # create an outside receiver reachable solely through the deliberately shared Unix socket
        receiver = """
import json, os, socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.bind('/exchange/receiver.sock')
os.chmod('/exchange/receiver.sock', 0o777)
print('ready', flush=True)
while True:
    print(json.dumps(s.recv(4096).decode()), flush=True)
"""
        self._docker(
            "run", "--detach", "--name", self.name, "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--mount", f"type=volume,src={self.name},dst=/exchange", self.IMAGE,
            "python", "-u", "-c", receiver,
        )
        deadline = time.monotonic() + 10
        while "ready" not in self._docker("logs", self.name):
            if time.monotonic() > deadline:
                raise RuntimeError("Synthetic receiver did not become ready")
            time.sleep(0.05)

        # demonstrate the control path so a failed send cannot be mistaken for a missing receiver
        control = "import socket; s=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM); s.sendto(b'control-marker','/exchange/receiver.sock')"
        run = (
            "run", "--rm", "--interactive", "--pull", "never", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "65534:65534", "--pids-limit", "64", "--memory", "128m",
            "--mount", f"type=volume,src={self.name},dst=/exchange,readonly", self.IMAGE, "python", "-I", "-",
        )
        self._docker(*run, source=control)

        boundary_path = self.root / "src/selene/isolation/linux_network.py"
        checks = """
import asyncio, json, os, socket, subprocess
os.closerange(3, 65536)
LinuxNetworkBoundary.apply()
results = {}
def denied(name, action):
    try:
        action()
    except PermissionError:
        results[name] = True
    else:
        raise AssertionError(name + ' unexpectedly allowed')
denied('ipv4_socket_denied', lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
denied('ipv6_socket_denied', lambda: socket.socket(socket.AF_INET6, socket.SOCK_STREAM))
denied('raw_socket_denied', lambda: socket.socket(socket.AF_PACKET, socket.SOCK_RAW))
channel = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
denied('unix_connect_denied', lambda: channel.connect('/exchange/receiver.sock'))
denied('unix_sendto_denied', lambda: channel.sendto(b'blocked-marker', '/exchange/receiver.sock'))
denied('unix_sendmsg_denied', lambda: channel.sendmsg([b'blocked-marker'], [], 0, '/exchange/receiver.sock'))
denied('unix_bind_denied', lambda: channel.bind('/exchange/new.sock'))
left, right = socket.socketpair()
left.sendall(b'private-wakeup')
assert right.recv(100) == b'private-wakeup'
left.close(); right.close()
results['private_socketpair_works'] = True
async def event_loop():
    return await asyncio.to_thread(lambda: 42)
assert asyncio.run(event_loop()) == 42
results['event_loop_thread_wakeup_works'] = True
child = subprocess.run([sys.executable, '-c', 'import socket; socket.socket(socket.AF_INET)'], capture_output=True, text=True)
assert child.returncode != 0 and 'PermissionError' in child.stderr
results['exec_child_inherits_denial'] = True
assert 'SELENE_SYNTHETIC_PARENT_SECRET' not in os.environ
results['parent_secret_not_inherited'] = True
assert os.getuid() == 65534
results['non_root'] = True
with open('/proc/self/status') as stream:
    status = stream.read()
assert 'NoNewPrivs:\\t1' in status and 'Seccomp:\\t2' in status
results['kernel_filter_and_no_new_privileges_active'] = True
print(json.dumps(results))
"""
        observations = json.loads(self._docker(*run, source=boundary_path.read_text() + "\n" + checks))
        received = self._docker("logs", self.name).splitlines()
        assert received == ["ready", '"control-marker"'], received
        observations["control_received_but_filtered_payload_not_received"] = True
        return {
            "observations": observations,
            "method": {
                "image": self.IMAGE,
                "source_sha256": hashlib.sha256(boundary_path.read_bytes()).hexdigest(),
                "synthetic_only": True,
                "model_calls": 0,
                "scope": "Real Linux ARM64 Docker processes, including an exec child and a separate Unix-socket receiver. "
                "No project or user-home mounts. This validates the network-filter component, not a complete Selene deployment.",
            },
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker-socket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    results = LinuxNetworkProbe(arguments.docker_socket).run()
    arguments.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
