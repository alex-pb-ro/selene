"""Fixed stdio startup inside Selene's isolated Linux image."""

import argparse
import json
import logging
import os
from pathlib import Path


class IsolatedServerBootstrap:
    """Start fixed stdio services after the container entrypoint applies process restrictions."""

    @classmethod
    def run(cls) -> None:
        parser = argparse.ArgumentParser(description="Selene inside the isolated local container")
        parser.add_argument("--context", choices=("desktop-app", "ide", "codex"), default="desktop-app")
        args = parser.parse_args()

        # keep runtime configuration and ordinary diagnostics out of persistent host storage
        os.umask(0o077)
        logging.disable(logging.CRITICAL)
        state = Path("/tmp/selene-state")
        state.mkdir(mode=0o700)
        os.environ["SELENE_HOME"] = str(state)
        os.environ["UV_OFFLINE"] = "1"
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        config = {
            "projects": [],
            "gui_log_window": False,
            "web_dashboard": False,
            "web_dashboard_open_on_launch": False,
            "trace_lsp_communication": False,
            "persist_symbol_cache": False,
            "log_level": "CRITICAL",
            "trusted_project_path_patterns": [],
            "token_count_estimator": "CHAR_COUNT",
            "record_tool_usage": False,
            "included_optional_tools": [
                "search_index",
                "find_context",
                "continue_context",
                "read_context_items",
                "analyze_change",
                "prepare_change",
                "apply_change",
                "recover_change",
            ],
            "ls_specific_settings": {"python": {"ls_path": "/opt/selene/.venv/bin/pyright-langserver"}},
        }
        (state / "selene_config.yml").write_text(json.dumps(config), encoding="utf-8")

        # import application services only after process restrictions are active
        from selene.config.selene_config import LanguageBackend
        from selene.mcp import SeleneMCPFactory

        factory = SeleneMCPFactory(transport="stdio", context=args.context, project="/workspace")
        server = factory.create_mcp_server(
            language_backend=LanguageBackend.LSP,
            enable_web_dashboard=False,
            enable_gui_log_window=False,
            open_web_dashboard=False,
            log_level="CRITICAL",
            trace_lsp_communication=False,
        )
        server.run(transport="stdio")
