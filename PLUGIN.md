# Selene agent plugin

Selene is packaged for GitHub Copilot App and CLI using Agent Plugins 1.0.
The same portable package supports current Codex clients, and a separate
compatibility manifest supports Claude Code. It includes a local stdio MCP
server and the `selene` skill.

## Requirements

- A client with support for the plugin format described below.
- `uv` available on the client's PATH and Python 3.11–3.14. `uv` can provision
  a compatible Python if one is not installed.
- Language-specific tooling required by the projects you analyze.

The first server start installs dependencies from the bundled `uv.lock` into
the client's persistent plugin data directory. It may take longer than later
starts. Dependencies may be downloaded; Selene's code and tool results remain
with the connected client. The plugin does not enable remote AI integrations.

## GitHub Copilot CLI

Register the checkout's bundled marketplace and install by name:

```sh
copilot plugin marketplace add /absolute/path/to/selene
copilot plugin install selene@selene-plugins
copilot plugin list
```

The marketplace lives inside this checkout at `.github/plugin/marketplace.json`;
no file in the checkout's parent directory is required. Start a new session after
installation. Use `/mcp` to check the server and ask:

> Use Selene: read its initial instructions, activate this project's absolute
> path, read its critical_info memory if present, and show its code structure.

Direct folder installation still works in Copilot CLI 1.0.83, but that client
marks it as deprecated. Use the marketplace commands above for new installations.

## GitHub Copilot App

Use **Customize → Plugins** to choose a marketplace and install Selene. The
bundled `.github/plugin/marketplace.json` lets this repository serve as that
marketplace. The app's documented **Add marketplace** flow accepts a GitHub
repository or Git URL, so those files must be present in the selected Git source.
Preparing the local checkout does not publish them.

For local-only development, use the CLI installation above. Copilot App also
documents that skills and MCP servers configured for Copilot CLI or a repository
are available in the app. Check **Customize → Installed** for Selene's components
after restarting; do not assume a separately configured app has imported a CLI
marketplace. If the app does not expose the plugin, its **Customize → MCP** flow
can launch the checkout directly with `uv` and these arguments:

```text
run --project /absolute/path/to/selene --locked --no-dev --no-env-file selene start-mcp-server --context copilot-cli --enable-web-dashboard false --open-web-dashboard false --enable-gui-log-window false
```

This manual MCP fallback uses the checkout's virtual environment. Use the same
initialization prompt above. App UI installation is a separate verification step
from CLI installation; see the validation notes below.

## Codex (optional)

Register the bundled Codex marketplace and install the plugin:

```sh
codex plugin marketplace add /absolute/path/to/selene
codex plugin add selene@selene-plugins
```

Then start a new thread. The portable `mcp.json` supplies the server; the
`.codex-plugin/plugin.json` manifest supplies Codex presentation metadata. The
shared server uses the `copilot-cli` context, which provides semantic tools
alongside a coding client's built-in file and shell tools.

## Claude Code (optional)

For a single session:

```sh
claude --plugin-dir /absolute/path/to/selene
```

For a persistent installation:

```sh
claude plugin marketplace add /absolute/path/to/selene
claude plugin install selene@selene-plugins
```

Start a new session and use `/mcp` to check the server. The Claude manifest has
its own MCP definition with Claude's plugin path variables and the `claude-code`
context. It shares the same runtime sources, lockfile, and skill.

## Runtime behavior

- Copilot and Codex resolve `${PLUGIN_ROOT}` to the installed package and
  `${PLUGIN_DATA}` to writable plugin storage. Claude uses its corresponding
  `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}` variables.
- `uv run --project` locates the bundled Python project. The runtime environment
  is stored under the client's plugin data directory, so the package does not
  need a prebuilt `.venv` or a separately installed `selene` executable.
- The server starts without an active project. The skill calls
  `initial_instructions`, activates the user's actual workspace by absolute
  path, and reads its `critical_info` memory. The plugin cache is not treated as
  the user's workspace.
- The dashboard and GUI log window are disabled. Existing Selene configuration
  and logs continue to use `~/.selene` or the user's `SELENE_HOME`; project data
  stays in the activated project's `.selene/` directory.
- This package does not install permission hooks or automatically approve tools.

If `uv` cannot be found by a desktop client, supply its absolute executable path
in that client's MCP configuration. If dependency setup exceeds a client's
startup timeout, allow setup to complete and restart the server or increase that
client's MCP startup timeout. An offline first start requires cached dependencies
and a compatible Python installation.

## Build a clean local distribution

From the checkout:

```sh
python3 scripts/build_plugin.py
```

This creates `dist/selene/` and `dist/selene.zip`, including the runtime sources,
lockfile, skill, and all three clients' catalogs. Development environments, Git
history, project memories, tests, and audit logs are not packaged. Install the
directory, or extract the ZIP before installing; the ZIP is a local distribution
artifact, not a registry publication.

The builder refuses to overwrite existing outputs. For another build, choose a
new destination with `--output /absolute/path/to/new-build/selene`.

## Validation

The initial package was checked locally on macOS with:

- Agent Plugins 1.0 schemas and the Codex and Claude manifest validators.
- Copilot CLI 1.0.83: marketplace installation, skill discovery, and MCP discovery.
- Codex: marketplace installation and actual MCP startup with 25 available tools.
- Claude Code: marketplace installation and discovery of its MCP definition.
- Both MCP configurations: initialization, explicit project activation, memory
  reading, symbol navigation, and a symbol edit in a temporary Python project.

Client installation checks used isolated configuration directories with network
access blocked. MCP tests used a clean built package and separate runtime storage.
Copilot App was not installed on the validation machine, so its UI installation
remains to be checked. Verify Selene in the app's plugin and MCP views after
installation.

## Format references

- [GitHub Copilot plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [Copilot App customization](https://docs.github.com/en/copilot/how-tos/github-copilot-app/customize-github-copilot-app)
- [Agent Plugins schemas](https://agent-plugins.org/)
- [Codex plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Claude Code plugin reference](https://code.claude.com/docs/en/plugins-reference)
