# Selene

Selene is a local MCP server for semantic code search, navigation, editing, and project memories.
It is a clone of [Serena](https://github.com/oraios/serena).

Selene uses language servers to give your chosen AI agent symbol-aware tools across more than 40 programming languages. Code and tool results are returned to the MCP client you connect. Usage statistics are calculated locally.

## Install as an agent plugin

For GitHub Copilot CLI, register this checkout's marketplace and install Selene:

```sh
copilot plugin marketplace add /absolute/path/to/selene
copilot plugin install selene@selene-plugins
```

The package also includes marketplace catalogs for GitHub Copilot App, Codex,
and Claude Code, plus a skill that initializes Selene for the working project.
Install `uv` first. See the [plugin guide](PLUGIN.md) for client-specific setup,
runtime requirements, and building a clean distribution.

## Run from this checkout

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.11–3.14, then run:

```sh
cd /absolute/path/to/selene
uv sync --locked
uv run --no-sync selene --help
uv run --no-sync selene start-mcp-server --project /absolute/path/to/your/project --context ide --open-web-dashboard false
```

For a typical MCP client, use this configuration, replacing both absolute paths:

```json
{
  "mcpServers": {
    "selene": {
      "command": "uv",
      "args": [
        "run", "--directory", "/absolute/path/to/selene", "--no-sync",
        "selene", "start-mcp-server",
        "--project", "/absolute/path/to/your/project",
        "--context", "ide", "--open-web-dashboard", "false"
      ]
    }
  }
}
```

Choose a client context such as `claude-code`, `codex`, or `ide` with `selene context list`. Alternatively, install the checkout as a command with `uv tool install /absolute/path/to/selene`. This fork is not published to a package registry; install from this checkout, not a similarly named online package.

Configuration and logs live in `~/.selene` (override with `SELENE_HOME`). Project configuration, memories, and caches use `.selene/`. See the [installation guide](docs/02-usage/010_installation.md), [client setup](docs/02-usage/030_clients.md), and [configuration guide](docs/02-usage/050_configuration.md).

See [cancellation and timeouts](docs/02-usage/071_cancellation.md) for operation ordering, cleanup and recovery after an interrupted edit.

See [source freshness](docs/02-usage/072_source_freshness.md) for external-edit detection, unsaved-buffer conflicts and synchronization limits.

For local stdio operation with enforced subprocess network restrictions, use the [isolated deployment](docs/02-usage/073_isolated_stdio.md).

## Privacy

The fork removes startup usage reporting, remote dashboard news and advertising, dashboard update checks, and API-based token counting. Dashboard scripts are bundled locally; the browser does not need third-party fonts or scripts.

Language servers and package managers can still download dependencies, compilers, project modules, and remote metadata. Automatic JSON/YAML schema downloads are disabled. Optional AI integrations send conversations to the provider you choose. User-configured commands and separately installed IDE plugins execute outside Selene's control. Selene is not a network sandbox.

The [security audit](SECURITY_AUDIT.md) documents findings, remediations, every reviewed network surface, verification, and remaining limitations. Agent instructions prohibit sending code, logs, memories, credentials, or diagnostics to another service without an explicit user request.

## Development

```sh
uv sync --locked --extra dev
uv run --no-sync poe format
uv run --no-sync poe type-check
uv run --no-sync poe test
```

Language integration tests are selected using pytest markers. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT; see [LICENSE](LICENSE). Original copyright notices are preserved.
