"""Verify cancellation and ping responsiveness over actual stdio MCP, using synthetic data."""

import asyncio
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

import psutil
from oslex import join as convert_shell_cmd


class CancellationProbe:
    def __init__(self):
        self.root = Path(__file__).resolve().parents[2]
        self.base = Path(tempfile.mkdtemp(prefix="selene-cancellation-"))
        self.responses = {}

    async def send(self, value):
        self.process.stdin.write((json.dumps(value) + "\n").encode())
        await self.process.stdin.drain()

    async def response(self, request_id, timeout=3):
        async with asyncio.timeout(timeout):
            while request_id not in self.responses:
                line = await self.process.stdout.readline()
                if not line:
                    raise RuntimeError("MCP server closed stdout")
                value = json.loads(line)
                if "id" in value:
                    self.responses[value["id"]] = value
        return self.responses.pop(request_id)

    async def run(self):
        project = self.base / "project"
        (project / ".selene").mkdir(parents=True)
        (project / ".selene/project.yml").write_text("project_name: cancellation-probe\nlanguage_servers: []\n")
        pid_path = project / "child.pid"
        late_effect = project / "late-effect.txt"
        code = (
            "import os, time; from pathlib import Path; "
            f"Path({str(pid_path)!r}).write_text(str(os.getpid())); time.sleep(30); "
            f"Path({str(late_effect)!r}).write_text('unwanted late effect')"
        )
        args = [
            str(self.root / ".venv/bin/selene"), "start-mcp-server", "--project", str(project),
            "--enable-web-dashboard", "false", "--enable-gui-log-window", "false", "--log-level", "ERROR",
            "--tool-timeout", "1",
        ]
        env = {**os.environ, "SELENE_HOME": str(self.base / "home"), "PYTHONPATH": str(self.root / "src")}
        with (self.base / "server-stderr.log").open("w") as stderr:
            self.process = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr, env=env
            )
            child = None
            try:
                await self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-11-25", "capabilities": {},
                    "clientInfo": {"name": "local-cancellation-probe", "version": "1"},
                }})
                initialized = await self.response(1)
                assert "result" in initialized, initialized
                await self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
                await self.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                    "name": "execute_shell_command", "arguments": {"command": convert_shell_cmd([sys.executable, "-c", code])},
                }})
                async with asyncio.timeout(3):
                    while not pid_path.exists():
                        await asyncio.sleep(0.01)
                child = psutil.Process(int(pid_path.read_text()))

                ping_started = time.perf_counter()
                await self.send({"jsonrpc": "2.0", "id": 3, "method": "ping"})
                assert "result" in await self.response(3, timeout=1)
                ping_ms = (time.perf_counter() - ping_started) * 1000

                cancel_started = time.perf_counter()
                await self.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {
                    "requestId": 2, "reason": "Synthetic cancellation verification",
                }})
                cancelled = await self.response(2)
                assert cancelled.get("error", {}).get("message") == "Request cancelled", cancelled
                await self.send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                    "name": "list_memories", "arguments": {},
                }})
                following = await self.response(4, timeout=5)
                assert "result" in following and not following["result"].get("isError"), following
                resumed_ms = (time.perf_counter() - cancel_started) * 1000
                child_stopped = not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
                assert child_stopped
                assert not late_effect.exists()
                # exercise the configured deadline without a client cancellation notification
                pid_path.unlink()
                await self.send({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
                    "name": "execute_shell_command", "arguments": {"command": convert_shell_cmd([sys.executable, "-c", code])},
                }})
                async with asyncio.timeout(3):
                    while not pid_path.exists():
                        await asyncio.sleep(0.01)
                child = psutil.Process(int(pid_path.read_text()))
                timed_out = await self.response(5)
                assert timed_out.get("result", {}).get("isError"), timed_out
                error_text = " ".join(item.get("text", "") for item in timed_out["result"].get("content", []))
                assert "timed out" in error_text, timed_out
                await self.send({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
                    "name": "list_memories", "arguments": {},
                }})
                after_timeout = await self.response(6)
                assert "result" in after_timeout and not after_timeout["result"].get("isError"), after_timeout
                stopped_on_timeout = not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
                assert stopped_on_timeout
                assert not late_effect.exists()

                # disconnect while another command is running; shutdown must drain cleanup
                pid_path.unlink()
                await self.send({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
                    "name": "execute_shell_command", "arguments": {"command": convert_shell_cmd([sys.executable, "-c", code])},
                }})
                async with asyncio.timeout(3):
                    while not pid_path.exists():
                        await asyncio.sleep(0.01)
                child = psutil.Process(int(pid_path.read_text()))
                self.process.stdin.close()
                await asyncio.wait_for(self.process.wait(), timeout=6)
                stopped_on_disconnect = not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
                assert stopped_on_disconnect
                assert not late_effect.exists()
                files = [
                    "src/selene/task_executor.py", "src/selene/mcp.py", "src/selene/util/cancellation.py",
                    "src/selene/util/shell.py", "src/selene/agent.py",
                ]
                result = {
                    "protocol": initialized["result"]["protocolVersion"],
                    "ping_during_slow_tool_ms": round(ping_ms, 3),
                    "next_tool_after_cancellation_ms": round(resumed_ms, 3),
                    "child_stopped_before_next_tool_returned": child_stopped,
                    "configured_timeout_returned_tool_error": True,
                    "child_stopped_before_next_tool_after_timeout": stopped_on_timeout,
                    "child_stopped_before_server_exit_on_disconnect": stopped_on_disconnect,
                    "late_effect_occurred": late_effect.exists(),
                    "platform": platform.platform(), "python": platform.python_version(), "model_calls": 0,
                    "scope": "Actual stdio MCP and a synthetic local shell child. No language servers or Internet calls. Not an OS egress audit.",
                    "source_sha256": {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in files},
                }
                output = self.root / "research/cancellation-results.json"
                output.write_text(json.dumps(result, indent=2) + "\n")
                print(output.read_text())
            finally:
                if child is not None:
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                self.process.stdin.close()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()


if __name__ == "__main__":
    asyncio.run(CancellationProbe().run())
