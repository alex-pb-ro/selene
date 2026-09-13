# Cancellation verification

Verified on macOS 26.6 (arm64), Python 3.11.15, MCP SDK 1.28.1 and AnyIO 4.13.0. The AnyIO dependency is now explicit; its previously locked version is unchanged.

| Check | Result |
| --- | --- |
| `uv run --no-sync poe format` | Pass |
| `uv run --no-sync poe type-check` | Pass |
| Core test selection via `security/probes/run_core_tests.py` | 996 passed, 11 skipped, 1,242 deselected; 157 seconds |
| `uv lock --check --offline` | Pass; no dependency version changes |
| Real stdio MCP ping during a slow tool | Pass; 1.525 ms in this run |
| Next tool after explicit request cancellation | Pass; 25.588 ms; shell child stopped |
| Configured one-second operation timeout | Returned a tool error; child stopped before the following tool completed |
| Client disconnect during a shell command | Child stopped before the MCP server exited |
| Delayed synthetic file write after cancellation/timeout/disconnect | Did not occur |

The core selection ran with `UV_OFFLINE=1` and permission for local loopback listeners and language-server cache files. An initial sandboxed run failed on those environment restrictions; the final run above passed after the shutdown changes. This is the repository's core selection, not all language/platform integration tests.

Run `uv run --no-sync python research/probes/cancellation.py` from the checkout to repeat the protocol checks. The probe creates only synthetic projects in a temporary directory and invokes no AI model. [cancellation-results.json](cancellation-results.json) records the observations and source hashes. The historical optimization baseline is unchanged.

The tests exercise ownership until execution stops, inherited and queued cancellation, deadline handling, callback ordering, shutdown, write checkpoints, a POSIX child that ignores `SIGTERM`, and retry policy after a language-server failure. See the [behavior and limits](../docs/02-usage/071_cancellation.md), particularly remote IDE operations, deliberately detached processes, Windows and uncooperative code. These checks do not establish OS-wide egress confinement or coding-task success improvements.
