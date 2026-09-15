---
name: selene
description: Use Selene's local MCP tools to find code symbols and references, make symbol-aware edits, or consult project memories. Use when the user requests Selene or code work benefits from language-server navigation.
---

# Selene

Use the Selene MCP server bundled with this plugin. The client may prefix its
tool names; discover the actual tools and schemas before calling them.

## Start a session

1. Call `initial_instructions` before using other Selene tools, and follow the
   returned guidance. Do this again in a new session if the instructions have
   not been loaded.
2. Identify the user's working project from the current task or client workspace.
   Call `activate_project` with its absolute path. The installed plugin directory
   is Selene's runtime, not the project to analyze. The plugin deliberately starts
   without an active project because clients may launch MCP servers from a cache.
3. Read the project's `critical_info` memory when present. It may already be
   included in the activation result; otherwise use `read_memory`.
4. Follow the returned onboarding guidance before working on that project.

## Work with code

Use `get_symbols_overview` to orient within a file, `find_symbol` to inspect a
definition, and `find_referencing_symbols` to trace its uses. Request symbol bodies
only when needed. For an edit to a known symbol, use the appropriate symbol editing
tool. Use the client's own tools for tasks outside Selene's capabilities and run
the project's required checks after changes.

Consult relevant project memories and follow the project's rules for updating
them. Keep code, tool results, logs, and memories with the connected client; do not
forward them to another service without the user's explicit request.

If the server is unavailable, report the connection failure and consult the
[plugin installation guide](../../PLUGIN.md). Do not substitute a similarly named
registry package.
