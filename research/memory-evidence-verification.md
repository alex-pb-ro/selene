# Memory evidence verification

The implementation is on local branch `feat/evidence-memory`, based on recoverable-edit commit `d2780f0`. It extends Markdown memories with optional source evidence and adds `check_memory` and `review_memory`. PR publication remains held because the requested main checkout no longer contains the original source.

## Acceptance evidence

The final affected selection passed **259 tests** on macOS, covering memory behavior, existing memory management, dashboard HTTP behavior, file writes, MCP construction/execution and the three compatibility contexts. Formatting and type checks passed. The established offline core selection passed **1,116 tests**, with **13 skipped** and **1,253 deselected**, in 160.36 seconds. Three additional storage/format boundary tests were then added and passed in the final affected selection; production code did not change after that core run.

| Requirement | Observed behavior |
| --- | --- |
| Scoped durable decisions | A Markdown record retains declared owner/origin, project binding, scope, source references, body hash and review time; no source body is automatically copied into the metadata |
| Source staleness | Changed bytes are detected despite preserved timestamps; missing, excluded and retargeted source references cease to be current; exact byte reversion can restore current status |
| Review after editing | Direct body changes, ordinary memory writes, reference maintenance and dashboard edits retain the old provenance and produce `needs_review` |
| Explicit source review | Old evidence cannot be refreshed implicitly; clients must supply current references and the current raw-memory hash |
| Cross-project applicability | A copied record's body is withheld until explicit adoption with current destination evidence; root aliases for the same project continue working |
| Scope boundaries | Evidenced records cannot move to global scope or through memory-path symlink aliases; read-only and ignored-memory rules apply to recording, moving and reviewing |
| Local retention | Writes use `0600`; expired records remain; a full 256-record store rejects additions while permitting existing review, and explicit removal frees capacity |
| Compatibility | Ordinary Markdown remains readable; upgrading it requires the observed raw-memory hash; CRLF hashes are exact; editor-added BOM/leading whitespace does not disable provenance |
| Invalid input | Invalid source ranges/scopes are rejected; an oversized body edit preserves the existing file; unknown provenance format fails rather than exposing an unassessed claim; named pipes are rejected without waiting for a writer |
| Presentation | Metadata markup remains JSON data; the dashboard edits only the body, displays review status, submits the loaded memory hash and disables saving a withheld body |

The first broader run exposed a schema-adapter problem: nullable nested provenance lacked a top-level type. Its existing nullable simplification also discarded branch constraints. The adapter now exposes a referenced definition's type while keeping the reference, and retains the non-null branch's complete schema. A client-facing test validates and executes nested provenance, including an omitted optional record, and rejects malformed evidence. All existing compatibility-context checks pass.

## Packaged stdio MCP and data handling

[isolated-memory-mcp-results.json](isolated-memory-mcp-results.json) records an actual MCP session with the rebuilt local Linux image. The server advertised **39 tools**. The synthetic scenario recorded a memory, edited its body, rejected a stale review precondition, explicitly reviewed it, applied a prepared source change, observed stale evidence and reviewed the changed source. A new container then rolled back the source change, observed the memory becoming stale again and accepted another explicit review. This exercises persistence and project binding across processes/containers on the tested shared filesystem.

Existing index, context, impact, recoverable-edit, managed-shell network-denial, outside-project symlink, inherited-environment and logging checks also passed. The explicit decision canary remained only in its private memory file. The source canary remained only in the explicit private change journal. Both were absent from client stderr, Docker daemon logs and other inspected project metadata. Requested source and memory results were returned to the connected test client over stdio.

The tested immutable image is `sha256:d44c3e3d25949d48ee8af0cc5cb68dff2d5e440b3af967618318b964c69991eb`. All **63** recorded runtime/build/probe hashes matched the final checkout after verification. The dedicated audit VM used only synthetic shared fixtures and was stopped after testing. No source, image or result was published; no model API was called. This is an execution-boundary check, not a provider-contract audit, full packet capture or proof about every possible native dependency configuration.

## Dashboard verification

[memory-dashboard-results.json](memory-dashboard-results.json) records a headless browser check against the actual bundled dashboard assets. All HTTP responses were intercepted locally and filled with synthetic data; other origins were rejected. No live project or user browser profile was used. The test exercised the visible stale notice, edit/save payload, dark-theme scope-mismatch state, withheld body and disabled save action. No page errors occurred. Both screenshots were visually inspected after the modal's JavaScript animation completed:

- [Stale evidence, light theme](memory-dashboard-stale.png).
- [Foreign record withheld, dark theme](memory-dashboard-scope.png).

The report records the dashboard HTML, JavaScript, CSS and probe hashes. This checks these memory interactions; it is not a full browser matrix or accessibility certification. Separate Flask tests verify the real HTTP handlers, including rejecting a stale memory version and keeping assessment text out of the saved body.

## Reproduction

Use the existing environment without syncing dependencies:

```sh
PYTHONPATH=src UV_OFFLINE=1 UV_CACHE_DIR=/tmp/selene-uv-cache SELENE_HOME=/tmp/selene-memory-tests \
  uv run --no-sync poe test test/selene/test_memory_evidence.py test/selene/test_memories_manager.py \
  test/selene/test_dashboard.py test/selene/util/test_file_system.py \
  test/selene/test_mcp.py test/selene/test_tool_parameter_types.py
```

`security/probes/run_core_tests.py` defines the established core selection. `scripts/build_isolated.py` and `security/probes/isolated_mcp.py` reproduce the isolated image/session with a local Docker socket and synthetic fixture root. `research/probes/memory_dashboard.cjs` requires Playwright and an existing local Chromium-compatible executable through `SELENE_BROWSER_EXECUTABLE`; it does not download a browser. Its screenshots and JSON result must be collected together with matching source hashes.

## Practical limits

Source-version validation is local, on demand and conservative. It does not authenticate owner declarations, verify semantic claims, infer corporate policy, generate summaries or measure agent task success. Source hashes cover complete files; unrelated edits within a cited file therefore mark it stale. Statuses are observations and do not prevent changes after the check returns.

The project binding uses canonical root plus filesystem identity, so moves, replacement roots or another clone require explicit adoption. It is editable local metadata, not protection against a person who can deliberately rewrite it. Provenance stays in the same Markdown file as the body and imposes no new database or network dependency. Ordinary global-memory behavior remains available separately.

Memory writes use the existing single-file atomic replacement helper and an observed raw-memory hash precondition. They do not use the recovery journal, keep an automatic prior version or implement compare-and-swap against arbitrary external editors. The 256-record limit is a soft admission check; it is not a cross-process storage quota. Unsupported/malformed provenance requires deliberate local repair. Native deployment remains unconfined; the isolated profile supplies the inherited network boundary and suppresses incidental logging.

Prompt templates and existing project memory files were not changed. No task-success or token-saving benefit is claimed for this feature. The [usage contract](../docs/02-usage/078_memory_evidence.md) describes supported inputs, statuses, retention and adoption.
