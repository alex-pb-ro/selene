# JetBrains compatibility backend

Selene retains an optional HTTP client for a separately installed compatible JetBrains plugin.
The plugin itself is not included in this repository, has not been audited here, and is not
published or sold by this fork. Use the default language-server backend for the audited source path.

If you already have a compatible plugin, the configuration below selects it. By default, the
client contacts loopback ports only. A configured remote plugin address receives project paths,
queries, edits, and debugging expressions. Review that plugin and its licensing, networking,
and telemetry separately before entrusting it with project data.

(configure-jetbrains)=
## Configuring Selene to Use the JetBrains Plugin

After installing the plugin, you need to configure Selene to use it.

**Central Configuration**.

You can run

```shell
selene init -b JetBrains
```

to set the default code intelligence backend to JetBrains in the global Selene configuration file.

Alternatively, manually edit the configuration file  `~/.selene/selene_config.yml`
(`%USERPROFILE%\.selene\selene_config.yml` on Windows) and set

```yaml
language_backend: JetBrains
```

Note that the file might not exist yet if you never executed Selene before.

**Per-Instance Configuration**.
The configuration setting in the global config file can be overridden on a
per-instance basis by providing the arguments `--language-backend JetBrains` when
launching the Selene MCP server.

(per-project-language-backend)=
**Per-Project Configuration**.
You can also set the language backend on a per-project basis in the project's
`.selene/project.yml` file:

```yaml
language_backend: JetBrains
```

If set, this overrides the global `language_backend` setting for the session when the project is
activated at startup (via the `--project` flag).

:::{important}
The language backend is determined once at startup and cannot be changed during a running session.
If a project with a different backend is activated after startup, Selene will return an error.

If you need to work with projects that use different backends, you can either:
1. Use the `--project` flag to activate the project at startup, which will use its configured backend.
2. Configure separate MCP server instances (one per backend) in your client.
:::

**Verifying the Setup**.
You can verify that Selene is using the JetBrains plugin by either checking the dashboard, where
you will see `Languages:
Using JetBrains backend` in the configuration overview.
You will also notice that your client will use the JetBrains-specific tools like `jet_brains_find_symbol` and others like it.

(jetbrains-workflow)=
## Workflow

Having installed the plugin in your IDE and having configured Selene to use the JetBrains backend,
the general workflow is simple:

1. Open the project you want to work on in your JetBrains IDE.<br>
   Note that the project must be appropriately set up in your IDE, i.e. symbol lookups for all relevant programming languages and frameworks should work in the IDE.<br>

   You can optionally make Selene open an IDE instance for your project root folder automatically upon project activation, allowing you to skip this step for a project that was previously set up correctly.
   To enable this, configure `jetbrains_launch_command` in [Selene's global configuration file](global-config) appropriately.
2. Activate the project's root folder as a project in Selene (see [Project Creation](project-creation-indexing) and [Project Activation](project-activation)).
3. Start using Selene's tools as usual.

Note that the project folder that is open in your IDE and the Selene project root folder must match.

:::{tip}
If you need to work on multiple projects in the same agent session, create a monorepo folder
containing all the projects and open that folder in both Selene and your IDE.
:::

## Advanced Usage and Configuration

### Using Selene with Multi-Module Projects

JetBrains IDEs support *multi-module projects*, where a project can reference other projects as modules.
Selene, however, requires that a project is self-contained within a single root folder.
There has to be a one-to-one relationship between the project root folder and the folder that is open in the IDE.

Therefore, to get a multi-module setup working with Selene, the recommended approach is to create a **monorepo folder**,
i.e. a folder that contains all the projects as sub-folders, and open that monorepo folder in both Selene and your IDE.

You do not necessarily need to physically move your projects into a common parent folder;
you can also use symbolic links to achieve the same effect
(i.e. use `mklink` on Windows or `ln` on Linux/macOS to link the project folders into a common parent folder).

### Using Selene with Windows Subsystem for Linux (WSL)

JetBrains IDEs have built-in support for WSL, allowing you to run the IDE on Windows while working with code in the WSL environment.
The Selene JetBrains plugin works seamlessly in this setup as well.

#### Using JetBrains Remote Development

Recommended constellation:
* Your project is in the WSL file system
* Selene is run in WSL (not Windows)
* The IDE has a host component (in WSL) and a client component (on Windows).<br>
  The Selene JetBrains plugin should normally be **installed in the host** (not the client) for code intelligence to be accessible.

:::{admonition} Plugin Installation Location
:class: note
If the plugin is already installed, check the options on the button for disabling the plugin.
Choose the respective options to ensure the correct installation location (i.e. host, removing it from the client if necessary).
:::

:::{admonition} Using mapped Windows paths in WSL is not recommended!
:class: warning
Keeping your project in the Windows file system and accessing it via `/mnt/` in WSL is extremely slow and not recommended.
:::

**Special Network Setup**.
If you are using a special setup where Selene and the IDE are running on different machines,
make sure Selene can communicate with the JetBrains plugin.
You can configure `jetbrains_plugin_server_address` in your [selene_config.yml](050_configuration) and
configure the listen address of the JetBrains plugin in the IDE via Settings / Tools / Selene
(e.g. set it to 0.0.0.0 to listen on all interfaces, but be aware of the security implications of doing so).

#### Other WSL Integrations (e.g. WSL interpreter)

* Your project is in the Windows file system
* WSL is used only for running tools (e.g. using a WSL Python interpreter in the IDE)
* Selene, the IDE and the plugin are all running on Windows

In this constellation, no special setup is required.

## Selene Plugin Configuration Options

You can configure plugin options in the IDE under Settings / Tools / Selene.

 * **Listen address** (default: `127.0.0.1`)<br>
   the address the plugin's server listens on.<br>
   The default will work as long as Selene is running on the same machine (or on a virtual machine using mirrored networking).
   But if the Selene MCP server is running on a different machine, configure the listen address to ensure that connections are possible.
   You can use `0.0.0.0` to listen on all interfaces (but be aware of the security implications of doing so).

 * **Sync file system before every operation** (default: enabled)<br>
   whether to synchronise the file system state before processing requests from Selene.<br>
   This is important to ensure that the plugin does not read stale data, but it can have a performance impact,
   especially when using slow file systems (e.g. WSL file system while the IDE is running on Windows).
   Note, however, that without synchronisation being forced by the Selene plugin, you will have to ensure synchronisation yourself.
   Operations that apply changes to files in your project that are *not* made either in the IDE itself or by Selene may not be seen by the IDE.
   Normally, the IDE synchronises automatically when it has the focus, using file watchers to achieve this (though this may or may not work reliably for the WSL file system).
   Also, if you are working primarily in another application (e.g. AI chat), the IDE may not have the focus frequently.
   So when external changes are made to your project, you will have to either give the IDE the focus (if that works) or trigger a sync manually (right-click root folder / Reload from Disk).<br>
   Further, note that even an edit made using, for example, Claude Code's internal editing tools would count as an external modification.
   Only Selene's editing tools are "JetBrains-aware" and will tell the IDE to update the state of the edited file.
   So if you are making AI-based edits using tools other than Selene's tools, do make sure that the lack of synchronisation is not a problem if you decide to disable this option.

## Usage with Other Editors

We realize that not everyone uses a JetBrains IDE as their main code editor.
You can still take advantage of the JetBrains plugin by running a JetBrains IDE instance alongside your
preferred editor. Most JetBrains IDEs have a free community edition that you can use for this purpose.
You just need to make sure that the project you are working on is open and indexed in the JetBrains IDE,
so that Selene can connect to it.
