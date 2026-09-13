"""Build Selene's isolated image locally using an explicit source allowlist."""

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


class IsolatedImageBuilder:
    def __init__(self, docker_socket: Path):
        self.root = Path(__file__).resolve().parents[1]
        self.socket = docker_socket.resolve(strict=True)
        if not stat.S_ISSOCK(self.socket.stat().st_mode):
            raise ValueError("The Docker endpoint must be a local Unix socket")
        docker = shutil.which("docker")
        if docker is None:
            raise RuntimeError("Docker is required to build the isolated image")
        self.command = [docker, "--host", "unix://" + str(self.socket)]

    def build(self) -> str:
        # select source without sending checkout history, memories, logs or environment files to the builder
        tracked = subprocess.check_output(["git", "ls-files", "-z", "src"], cwd=self.root, text=True).split("\0")
        paths = {path for path in tracked if path}
        paths.update(str(path.relative_to(self.root)) for path in (self.root / "src/selene/isolation").glob("*.py"))
        paths.update(("pyproject.toml", "uv.lock", "LICENSE", "containers/isolated/Dockerfile", "containers/isolated/entrypoint.py"))
        with tempfile.TemporaryDirectory(prefix="selene-image-build-") as temporary:
            build_root = Path(temporary)
            context = build_root / "context"
            context.mkdir()
            for relative in sorted(paths):
                source = self.root / relative
                if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(self.root):
                    raise ValueError(f"Unexpected build input: {relative}")
                target = context / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

            # use an empty Docker configuration and never push the completed image
            configuration = build_root / "docker-config"
            configuration.mkdir()
            environment = {key: value for key, value in os.environ.items() if key in ("PATH", "LANG", "LC_ALL")}
            environment["DOCKER_CONFIG"] = str(configuration)
            subprocess.run(
                [
                    *self.command,
                    "build",
                    "--tag=selene-isolated:local",
                    "--file",
                    str(context / "containers/isolated/Dockerfile"),
                    str(context),
                ],
                env=environment,
                stdout=sys.stderr,
                check=True,
            )
            return subprocess.check_output(
                [*self.command, "image", "inspect", "selene-isolated:local", "--format={{.Id}}"], env=environment, text=True
            ).strip()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-socket", type=Path, required=True)
    arguments = parser.parse_args()
    print(IsolatedImageBuilder(arguments.docker_socket).build())
