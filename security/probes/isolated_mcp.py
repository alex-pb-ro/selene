"""Verify the isolated stdio image with a synthetic project shared by the local daemon."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class IsolatedMCPProbe:
    _IMAGE_SOURCES = (
        "src/selene/isolation/linux_network.py", "src/selene/isolation/bootstrap.py",
        "src/selene/config/selene_config.py", "src/selene/ls_manager.py", "src/selene/project.py",
        "src/solidlsp/ls.py", "src/solidlsp/settings.py", "containers/isolated/entrypoint.py", "LICENSE",
    )

    def __init__(self, fixture_root: Path, docker_socket: Path, image: str):
        self.root = Path(__file__).resolve().parents[2]
        self.fixture_root = fixture_root.resolve(strict=True)
        self.socket = docker_socket
        self.image = image

    @staticmethod
    def _text(result) -> str:
        return "\n".join(item.text for item in result.content if item.type == "text")

    @staticmethod
    def _python(source: str) -> str:
        return "python -c " + shlex.quote(source)

    def _daemon_logs(self, project: Path, approved: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="selene-probe-docker-") as configuration:
            environment = {"PATH": os.environ["PATH"], "DOCKER_CONFIG": configuration}
            command = ["docker", "--host", "unix://" + str(self.socket)]
            ids = subprocess.check_output(
                [*command, "ps", "--filter", "ancestor=" + self.image, "--format={{.ID}}"], env=environment, text=True,
            ).split()
            matches = []
            for container_id in ids:
                inspected = json.loads(subprocess.check_output([*command, "inspect", container_id], env=environment, text=True))[0]
                if any(mount.get("Source") == str(project) and mount["Destination"] == "/workspace" for mount in inspected["Mounts"]):
                    matches.append(inspected)
            assert len(matches) == 1, "Expected one container for the synthetic project"
            inspected = matches[0]
            logs = subprocess.run([*command, "logs", inspected["Id"]], env=environment, capture_output=True, text=True)
            assert approved not in logs.stdout and approved not in logs.stderr
            return {
                "source_canary_absent_from_daemon_logs": True,
                "docker_logging_driver": inspected["HostConfig"]["LogConfig"]["Type"],
                "docker_network_mode": inspected["HostConfig"]["NetworkMode"],
            }

    async def run(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="mcp-", dir=self.fixture_root) as directory:
            base = Path(directory)
            project = base / "project"
            project.mkdir()
            approved = "APPROVED_CLIENT_CANARY"
            outside = "OUTSIDE_WORKSPACE_CANARY"
            (project / "module.py").write_text(f'def visible_symbol():\n    return "{approved}"\n')
            (base / "outside.txt").write_text(outside)
            (project / "escape.txt").symlink_to("../outside.txt")
            stderr_path = self.fixture_root / "last-client-stderr.log"
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[
                    str(self.root / "scripts/run_isolated.py"),
                    "--project", str(project), "--docker-socket", str(self.socket), "--image", self.image,
                ],
                env={**os.environ, "SELENE_SYNTHETIC_PARENT_SECRET": "parent-only-canary"},
            )
            observations = {}
            with stderr_path.open("w") as stderr:
                async with stdio_client(parameters, errlog=stderr) as (read, write):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        observations["server_name"] = initialized.serverInfo.name
                        catalog = await session.list_tools()
                        observations["tool_count"] = len(catalog.tools)

                        source = await session.call_tool("read_file", {"relative_path": "module.py"})
                        assert not source.isError and approved in self._text(source), self._text(source)
                        observations["source_returned_to_connected_client"] = True

                        symbols = await session.call_tool("find_symbol", {
                            "name_path_pattern": "visible_symbol", "relative_path": "module.py", "include_body": True,
                        })
                        assert not symbols.isError and "visible_symbol" in self._text(symbols), self._text(symbols)
                        assert approved in self._text(symbols), self._text(symbols)
                        observations["local_pyright_symbol_body_returned"] = True

                        network = await session.call_tool("execute_shell_command", {
                            "command": self._python("import socket; socket.socket(socket.AF_INET)"),
                        })
                        network_output = json.loads(self._text(network))
                        assert network_output["return_code"] != 0 and "PermissionError" in network_output["stderr"], network_output
                        observations["managed_shell_network_denied"] = True

                        escape = await session.call_tool("read_file", {"relative_path": "escape.txt"})
                        assert outside not in self._text(escape)
                        assert "Error" in self._text(escape) or escape.isError, self._text(escape)
                        observations["outside_project_symlink_cannot_read_host_canary"] = True

                        inspect = await session.call_tool("execute_shell_command", {"command": self._python(
                            "import json,os; print(json.dumps({'uid':os.getuid(), 'secret_present': "
                            "'SELENE_SYNTHETIC_PARENT_SECRET' in os.environ, 'status':open('/proc/self/status').read()}))"
                        )})
                        inspect_output = json.loads(json.loads(self._text(inspect))["stdout"])
                        assert inspect_output["uid"] != 0 and not inspect_output["secret_present"]
                        assert "NoNewPrivs:\t1" in inspect_output["status"] and "Seccomp:\t2" in inspect_output["status"]
                        observations["shell_has_no_parent_secret_and_keeps_kernel_restrictions"] = True

                        created = await session.call_tool("create_text_file", {"relative_path": "created.py", "content": "value = 42\n"})
                        assert not created.isError and (project / "created.py").read_text() == "value = 42\n", self._text(created)
                        observations["authorized_project_edit_visible_on_host"] = True
                        observations.update(self._daemon_logs(project, approved))

                        image_paths = {
                            path: "/opt/selene/container_entrypoint.py" if path == "containers/isolated/entrypoint.py" else "/opt/selene/" + path
                            for path in self._IMAGE_SOURCES
                        }
                        hashes = await session.call_tool("execute_shell_command", {"command": self._python(
                            "import hashlib,json,pathlib; paths=" + repr(image_paths) + "; "
                            "print(json.dumps({p:hashlib.sha256(pathlib.Path(q).read_bytes()).hexdigest() for p,q in paths.items()}))"
                        )})
                        actual_hashes = json.loads(json.loads(self._text(hashes))["stdout"])
                        expected_hashes = {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in image_paths}
                        assert actual_hashes == expected_hashes
                        observations["tested_image_sources_match_checkout"] = True

            captured = stderr_path.read_text()
            assert approved not in captured and outside not in captured, captured
            observations["source_canaries_absent_from_client_stderr"] = True
            metadata = [path for path in (project / ".selene").rglob("*") if path.is_file()]
            assert not any(approved.encode() in p.read_bytes() for p in metadata)
            observations["source_canary_not_retained_in_project_metadata"] = True
            return {
                "observations": observations,
                "method": {
                    "image": self.image,
                    "synthetic_only": True,
                    "model_calls": 0,
                    "source_sha256": {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in (
                        *self._IMAGE_SOURCES, "scripts/run_isolated.py", "scripts/build_isolated.py", "containers/isolated/Dockerfile",
                    )},
                    "scope": "Real stdio MCP, cached local Pyright and managed shell in the isolated Linux image. "
                    "Host fixtures are synthetic; this is not a provider-contract audit or a full packet capture.",
                },
            }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--docker-socket", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(IsolatedMCPProbe(args.fixture_root, args.docker_socket, args.image).run())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
