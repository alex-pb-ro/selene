# Running Selene

Selene is a command-line tool with a variety of sub-commands.
This section describes
 * how to run Selene in general
 * how to run and configure the most important command, i.e. starting the MCP server
 * other useful commands.

The main way to run Selene is to use the [installed version](install-selene),
which should be available in your system PATH as `selene.`

In general, to get help, append `--help` to the command, i.e.

    selene --help
    selene <command> --help


(start-mcp-server)=
## Running the MCP Server

Given your preferred method of running Selene, you can start the MCP server using the `start-mcp-server` command:

    selene start-mcp-server [options]<br>

Note that no matter how you run the MCP server, Selene will, by default, start a web-based dashboard on localhost that will allow you to inspect
the server's operations, logs, and configuration.

:::{tip}
By default, Selene will use language servers for code understanding and analysis.<br>
With the [Selene JetBrains Plugin](025_jetbrains_plugin), we recently introduced a powerful alternative,
which has several advantages over the language server-based approach.
:::

### Standard I/O Mode

The typical usage involves the client (e.g. Claude Code, Codex or Cursor) running
the MCP server as a subprocess and using the process' stdin/stdout streams to communicate with it.
In order to launch the server, the client thus needs to be provided with the command to run the MCP server.

:::{note}
MCP servers which use stdio as a protocol are somewhat unusual as far as client/server architectures go, as the server
necessarily has to be started by the client in order for communication to take place via the server's standard input/output streams.
In other words, you do not need to start the server yourself. The client application (e.g. Claude Desktop) takes care of this and
therefore needs to be configured with a launch command.
:::

Communication over stdio is the default for the Selene MCP server, so in the simplest
case, you can simply run the `start-mcp-server` command without any additional options.

    selene start-mcp-server

See the section ["Configuring Your MCP Client"](030_clients) for specific information on how to configure your MCP client (e.g. Claude Code, Codex, Cursor, etc.)
to use such a launch command.

(streamable-http)=
### Streamable HTTP Mode

When using *Streamable HTTP* mode, you control the server lifecycle yourself,
i.e. you start the server and provide the client with the URL to connect to it.

Simply provide `start-mcp-server` with the `--transport streamable-http` option and optionally provide the desired port
via the `--port` option.
For example, to start the server on port 9121, run

    selene start-mcp-server --transport streamable-http --port <port>

and then configure your client to connect to `http://localhost:9121/mcp`.

By default, only connections from localhost are allowed; pass the `--host <listen_address>` option to configure
the listen address and allow remote connections if needed (but be aware of the security implications of doing so).

**When to use.** Note that Selene is a stateful MCP server, and only one coding project can be active at a time.
Therefore, starting a single Selene instance and connecting it to multiple clients is only
appropriate if all clients will be working on the same project.<br>
If you want several agents to work on different projects, making each client/agent start its own server
in stdio mode is likely the best option.
See section [The Project Workflow](040_workflow) for more information on how to manage projects in Selene.

The legacy SSE transport is also supported (via `--transport sse` with corresponding /sse endpoint), its use is discouraged.

(mcp-args)=
### MCP Server Command-Line Arguments

The Selene MCP server supports a wide range of additional command-line options.
Use the command

    <selene> start-mcp-server --help

to get a list of all available options.

Some useful options include:

  * `--project <path|name>`: specify the project to work on by name or path.
  * `--project-from-cwd`: auto-detect the project from current working directory<br>
    (walking up the parent directories and activating the nearest one that contains either `.selene/project.yml`
    or `.git`, if any). The nearest boundary wins, so a git worktree nested under another Selene project resolves
    to the worktree itself rather than the ancestor project.
    This option is intended for CLI-based agents like Claude Code, Gemini and Codex, which are typically started from within the project directory
    and which do not change directories during their operation.
  * `--language-backend JetBrains`: use the Selene JetBrains Plugin as the language backend (overriding the default backend configured in the central configuration)
  * `--context <context>`: specify the operation [context](contexts) in which Selene shall operate
  * `--mode <mode>`: specify one or more [modes](modes) to enable (can be passed several times)
  * `--open-web-dashboard <true|false>`: whether to open the web dashboard on startup (enabled by default)

## Other Commands

Selene provides several other commands in addition to `start-mcp-server`,
most of which are related to project setup and configuration.

To get a list of available commands, run:

    <selene> --help

To get help on a specific command, run:

    <selene> <command> --help

In general, add `--help` to any command or sub-command to get information about its usage and available options.

Here are some examples of commands you might find useful:

```bash
# get help about a sub-command
selene> tools list --help

# list all available tools
selene> tools list --all

# get detailed description of a specific tool
selene> tools description find_symbol

# creating a new Selene project in the current directory
selene project create

# creating and immediately indexing a project
selene project create --index

# indexing the project in the current directory (auto-creates if needed)
selene project index

# run a health check on the project in the current directory
selene project health-check

# check if a path is ignored by the project
selene project is_ignored_path path/to/check

# edit Selene's configuration file
selene config edit

# list available contexts
selene context list

# create a new context
selene context create my-custom-context

# edit a custom context
selene context edit my-custom-context

# list available modes
selene mode list

# create a new mode
selene mode create my-custom-mode

# edit a custom mode
selene mode edit my-custom-mode

# list available prompt definitions
selene prompts list

# create an override for internal prompts
selene prompts create-override prompt-name

# edit a prompt override
selene prompts edit-override prompt-name
```

Explore the full set of commands and options using the CLI itself!


## Alternative Ways of Running Selene

Depending on your requirements, you may want to run Selene in different ways.
When applying one of these approaches, replace `selene` in commands mentioned throughout the documentation
with the respective command and options. The same applies to `selene-hooks` commands.

### Running from local source

From the Selene checkout, install dependencies with `uv sync --locked` and run `uv run --no-sync selene <command>`.
From another directory use `uv run --directory /absolute/path/to/selene --no-sync selene <command>`.
Pass `--project /absolute/path/to/project` explicitly when starting the server this way.

(docker)=
### Using Docker

The Docker approach offers several advantages:

* better security isolation for shell command execution
* no need to install language servers and dependencies locally
* consistent environment across different systems

You can run the Selene MCP server directly via Docker as follows,
assuming that the projects you want to work on are all located in `/path/to/your/projects`:

```shell
docker build -t selene:local .
docker run --rm -i -v /path/to/your/projects:/workspaces/projects selene:local start-mcp-server
```

This command mounts your projects into the container under `/workspaces/projects`, so when working with projects,
you need to refer to them using the respective path (e.g. `/workspaces/projects/my-project`).

Alternatively, you may use Docker compose. Adjust the file `compose.yml`, which is provided in the repository, according to your needs.
See our {download}`advanced Docker usage <../../DOCKER.md>` documentation for more detailed instructions, configuration options, and limitations.

:::{note}
Docker usage is subject to limitations; see the {download}`advanced Docker usage <../../DOCKER.md>` documentation for details.
:::

### Using Nix to Run the Latest Source Version

If you are using Nix and [have enabled the `nix-command` and `flakes` features](https://nixos.wiki/wiki/flakes), you can run Selene using the following command:

```bash
nix run path:/absolute/path/to/selene -- <command> [options]
```

You can also install Selene by referencing this repo (`path:/absolute/path/to/selene`) and using it in your Nix flake. The package is exported as `selene`.
