"""Run a prebuilt Selene image through a controlled local Docker daemon over stdio."""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


class IsolatedContainerLauncher:
    """Expose one project to an immutable local image with no host credential forwarding."""

    def __init__(self, project: Path, docker_socket: Path, image: str, context: str):
        self.project = project.resolve(strict=True)
        self.socket = docker_socket.resolve(strict=True)
        if not self.project.is_dir():
            raise ValueError("The project must be a directory")
        if not stat.S_ISSOCK(self.socket.stat().st_mode):
            raise ValueError("The Docker endpoint must be a local Unix socket")
        if any(character in str(self.project) for character in (",", "\n", "\r")):
            raise ValueError("Docker mount paths containing commas or newlines are unsupported")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("Use the immutable local image ID reported by docker image inspect")
        docker = shutil.which("docker")
        if docker is None:
            raise RuntimeError("Docker is required for the isolated deployment")
        self.command = [docker, "--host", "unix://" + str(self.socket)]
        self.image = image
        self.context = context

    def run(self) -> int:
        # inspect the selected local artifact without consulting host registry credentials
        with tempfile.TemporaryDirectory(prefix="selene-docker-client-") as configuration:
            environment = {key: value for key, value in os.environ.items() if key in ("PATH", "LANG", "LC_ALL")}
            environment["DOCKER_CONFIG"] = configuration
            inspected = subprocess.run(
                [*self.command, "image", "inspect", self.image],
                capture_output=True,
                text=True,
                env=environment,
                check=True,
                timeout=15,
            )
            image = json.loads(inspected.stdout)[0]
            if image["Config"].get("Labels", {}).get("io.selene.isolation.profile") != "stdio-v1":
                raise ValueError("The selected image was not built for Selene's isolated stdio profile")

            # keep host mounts limited to the selected project and runtime writes in ephemeral storage
            user = os.getuid() if os.getuid() else 65534
            group = os.getgid() if os.getuid() else 65534
            command = [
                *self.command,
                "run",
                "--rm",
                "--interactive",
                "--init",
                "--pull=never",
                "--network=none",
                "--log-driver=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=256",
                "--memory=2g",
                "--cpus=2",
                f"--user={user}:{group}",
                "--tmpfs=/tmp:rw,nosuid,nodev,size=256m,mode=1777",
                "--mount",
                f"type=bind,src={self.project},dst=/workspace,bind-recursive=disabled",
                "--workdir=/workspace",
                "--entrypoint=/opt/selene/.venv/bin/python",
                self.image,
                "-I",
                "-S",
                "/opt/selene/container_entrypoint.py",
                "--context=" + self.context,
            ]
            return subprocess.run(command, check=False, env=environment, close_fds=True).returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--docker-socket", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--context", default="desktop-app")
    arguments = parser.parse_args()
    raise SystemExit(IsolatedContainerLauncher(arguments.project, arguments.docker_socket, arguments.image, arguments.context).run())
