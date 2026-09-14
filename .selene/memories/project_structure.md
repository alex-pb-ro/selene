# Selene — Project Core

Selene is an MCP-based "IDE for coding agents": semantic code retrieval/editing/refactoring tools driven by language servers.

## Source map

- `src/selene/` — agent, MCP server, tools, project/config layer
  - `agent.py`, `mcp.py`, `project_server.py`, `cli.py`, `hooks.py` — entrypoints/wiring
  - `tools/` — tool implementations (memory_tools, symbol_tools, file_tools, workflow_tools, query_project_tools, config_tools, cmd_tools, jetbrains_tools)
  - `tools/tools_base.py` — base classes for all tools
  - `config/` — `selene_config.py`, `context_mode.py`, `client_setup.py`
  - `resources/config/contexts/*.yml`, `resources/config/modes/*.yml` — context/mode definitions
  - `code_editor.py`, `symbol.py`, `ls_manager.py` — symbolic editing / LS lifecycle
  - `dashboard.py`, `gui_log_viewer.py` — web dashboard / log viewer
  - `prompt_factory.py` + `generated/generated_prompt_factory.py` — prompts (regenerate with `scripts/gen_prompt_factory.py`)
- `src/solidlsp/` — LSP client framework; per-language servers under `language_servers/`
- `src/interprompt/` — prompt template library (synced from external repo; see `.syncCommitId.*`)
- `test/selene/`, `test/solidlsp/<lang>/` — pytest suites; per-language tests gated by pytest markers
- `test/resources/repos/<lang>/` — fixture projects used by language-server tests
- `scripts/` — utilities (prompt regen, tool overview, profiling, agno agent)
- `docs/` — Jupyter Book sources; build via `poe doc-build`

## Project-wide invariants

- Package name (PyPI): `selene-agent`; Wheel includes `selene`, `interprompt`, `solidlsp`.
- Python: `>=3.11, <3.15`. Dependencies are exact-pinned in `pyproject.toml` (uvx installs from git, lockfile ignored — pin exactly).
- Entry points: `selene` → `selene.cli:top_level`; `selene-hooks` → `selene.hooks:hook_commands`.
