"""Observable privacy guarantees for startup, persistence, and local HTTP communication."""

import json
import pickle
import socket
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError

import pytest
import requests
from bs4 import BeautifulSoup

from selene.agent import SeleneAgent
from selene.analytics import ToolUsageStats
from selene.config.selene_config import SeleneConfig
from selene.dashboard import SeleneDashboardAPI
from selene.tools import InitialInstructionsTool
from selene.util.http import DirectHttpSession, DirectUrlOpener
from selene.util.logging import MemoryLogHandler
from solidlsp.ls import DocumentSymbols
from solidlsp.lsp_protocol_handler.lsp_types import SymbolKind
from solidlsp.util.cache import load_cache, save_cache
from solidlsp.util.subprocess_util import subprocess_run


def test_startup_instructions_statistics_and_dashboard_work_without_network(monkeypatch):
    attempts = []

    def reject(*args, **kwargs):
        attempts.append(args)
        raise OSError("Network disabled for privacy verification")

    monkeypatch.setattr(socket, "getaddrinfo", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)
    config = SeleneConfig().with_headless_mode_overrides()
    agent = SeleneAgent(selene_config=config)
    try:
        instructions = agent.get_tool(InitialInstructionsTool).apply_ex()
        assert "Selene Instructions Manual" in instructions
        assert "Do not send code" in instructions
        stats = ToolUsageStats()
        stats.record_tool_usage("find_symbol", "private source code", "private result")
        assert stats.get_stats("find_symbol").num_times_called == 1
        dashboard = SeleneDashboardAPI(MemoryLogHandler(), [], agent, stats)
        client = dashboard._app.test_client()
        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
        page = BeautifulSoup(response.data, "html.parser")
        for element in page.select("script[src], link[href], img[src]"):
            url = element.get("src") or element.get("href")
            assert not url.startswith(("http:", "https:", "//")), url
            assert client.get("/dashboard/" + url).status_code == 200, url
        assert client.get("/get_tool_stats").json["stats"]["find_symbol"]["num_times_called"] == 1
        assert attempts == [], f"Unexpected network attempts: {attempts}"
    finally:
        agent.on_shutdown()


@contextmanager
def _http_server(redirect_to: str | None = None):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.path)
            self.send_response(302 if redirect_to else 200)
            if redirect_to:
                self.send_header("Location", redirect_to)
            self.end_headers()
            self.wfile.write(b"local response")

        def log_message(self, format: str, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_project_http_bypasses_environment_proxy_and_rejects_redirects(monkeypatch):
    with _http_server() as (proxy, proxy_requests), _http_server() as (destination, destination_requests):
        monkeypatch.setenv("HTTP_PROXY", proxy)
        monkeypatch.setenv("ALL_PROXY", proxy)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("http_proxy", proxy)
        monkeypatch.setenv("all_proxy", proxy)
        monkeypatch.setenv("no_proxy", "")
        with DirectHttpSession() as session:
            assert session.get(destination, timeout=2).text == "local response"
            assert destination_requests == ["/"]
            with _http_server(destination + "/leak") as (redirect, redirect_requests):
                with pytest.raises(requests.HTTPError, match="Refusing to redirect"):
                    session.get(redirect, timeout=2)
                with pytest.raises(HTTPError):
                    DirectUrlOpener.create().open(redirect, timeout=2)
                assert redirect_requests == ["/", "/"]
        assert proxy_requests == []
        assert destination_requests == ["/"]


def test_subprocesses_receive_telemetry_opt_outs_even_if_parent_opts_in(monkeypatch):
    monkeypatch.setenv("DOTNET_CLI_TELEMETRY_OPTOUT", "0")
    monkeypatch.setenv("AGNO_TELEMETRY", "true")
    result = subprocess_run(
        [
            sys.executable,
            "-c",
            'import json,os; print(json.dumps({k: os.environ[k] for k in ("DOTNET_CLI_TELEMETRY_OPTOUT", "AGNO_TELEMETRY", "npm_config_audit")}))',
        ],
        check=True,
    )
    assert json.loads(result.stdout) == {"DOTNET_CLI_TELEMETRY_OPTOUT": "1", "AGNO_TELEMETRY": "false", "npm_config_audit": "false"}


def test_symbol_cache_roundtrip_preserves_values_and_rejects_executable_payloads(tmp_path: Path):
    cache = tmp_path / "symbols.pkl"
    symbols = DocumentSymbols([{"name": "local_symbol", "kind": SymbolKind.Function, "children": []}])
    save_cache(str(cache), (1, "fixture"), {"module.py": ("hash", symbols)})
    restored = load_cache(str(cache), (1, "fixture"))
    assert restored["module.py"][1].root_symbols == symbols.root_symbols

    marker = tmp_path / "executed.txt"

    class Payload:
        def __reduce__(self):
            return eval, (f"__import__('pathlib').Path({str(marker)!r}).write_text('unexpected execution')",)

    cache.write_bytes(pickle.dumps(Payload()))
    with pytest.raises(pickle.UnpicklingError, match="Forbidden cache global"):
        load_cache(str(cache), (1, "fixture"))
    assert not marker.exists()
