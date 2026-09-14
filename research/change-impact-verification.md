# Proposed-change impact verification

The optional `analyze_change` tool accepts an unapplied unified diff or version-preconditioned file replacements, creations and deletions. It returns changed symbols, static reference/implementation evidence, declared schema/generation dependencies, heuristic test candidates and unresolved behavior. Source files remain unchanged by analysis. Code bodies are not retained between requests, and no model or remote lookup service is added.

## Evidence

| Check | Result |
| --- | --- |
| Final input, impact and context selection | 35 passed in 10.79 seconds |
| Real Pyright impact cases within that selection | Renamed imports lead to both call sites on one line and indirect tests; changing or deleting an API preserves its original source; unrelated same-name functions stay outside semantic results |
| Real TypeScript interface case within that selection | Finds implementation methods, an injected-interface caller and its indirect test; excludes the unrelated same-name class |
| Schema and generation cases | A changed JSON pointer selects its local consumer but not an unaffected pointer; explicit generator mappings return versioned generated outputs; remote schemas remain unfetched and generation freshness remains unresolved |
| Proposed-change input cases | Exact diff matching, creation/deletion, missing final newline, CRLF/Unicode, source hash conflicts, preserved timestamps, ignored/external/duplicate aliases and preservation of unrelated content |
| Exact output allowance and scope | Omitted findings are counted, target scope is respected and the complete JSON length equals `budget.used` |
| Repository core selection | 1,067 passed, 13 skipped, 1,253 deselected in 158.05 seconds |
| Formatting, types and patch whitespace | Passed |
| Actual isolated MCP | 34 advertised tools; structured proposal accepted; existing references returned; source left unchanged; incorrect source hash rejected; preceding context/index checks passed |
| Existing privacy acceptance in the rebuilt image | Network creation denied, external host symlink unreadable, parent secret not forwarded, source canaries absent from client stderr, Docker logs and project metadata |

The final local image is `sha256:02072c2868cbab789a6f8813b725a228b72de3c8a77ac7c441cfeb9a9a4d454e`. The [MCP results](isolated-impact-mcp-results.json) compare actual image source hashes with the checkout and include the probe's hash. The image was not published and only synthetic files were shared with its dedicated VM.

The TypeScript fixture used TypeScript 5.9.3 and typescript-language-server 5.1.3, provisioned into a temporary test directory with npm lifecycle scripts, audit reporting and inherited user configuration disabled. These tools were installed before creating the synthetic project. They were not installed into the shared Python environment or added as package dependencies. Pyright 1.1.403 came from the existing offline cache. Native tests do not establish OS isolation; the separate packaged-image probe supplies the stated isolation evidence.

## Selection quality and a measured miss

The [evaluation probe](probes/change_impact.py) creates a required-parameter API change, an aliased caller, direct and indirect tests, and an opaque reflective call assembled from string fragments. The original broader test suite passes. Analysis runs on the original source, then separate synthetic copies receive the proposal so selected tests can be compared with a broader gate chosen independently of the report.

The [recorded result](change-impact-results.json) found all three expected static reference sites and both statically connected test files. The report used 7,477 JSON characters under a 30,000-character allowance and took 2,088.133 ms, including the backend's initial cross-file reference wait.

| Run | Tests | Failures after the proposal |
| --- | --- | --- |
| Original broader suite | 3 | 0 |
| Selected tests on a proposed-change copy | 2 | `test_direct`, `test_primary` |
| Independent broader suite on another proposed-change copy | 3 | `test_direct`, `test_primary`, `test_opaque` |

The selected tests missed **one real regression**, in the opaque reflective call. This is an observed limitation, not a complete-impact claim. The response explicitly retains unresolved dynamic behavior and calls for the independently configured broader regression gate. Runtime coverage integration, arbitrary-language recall and agent task-success evaluation are not established by this experiment. No tests were selected or skipped to make the broader gate agree with the analysis.

## Findings that changed the implementation

1. The inherited symbol-name matcher rejects an empty name. Whole-file enumeration now uses document symbols instead of presenting an unsupported empty-name search as a semantic result. This also corrects context retrieval with a path-only anchor.
2. Pyright reports a renamed import as a reference to the original declaration, while references to the local alias are a separate query. The provider now validates the import binding against the captured Python syntax and follows that binding. Alias edges retain evidence and consume no caller depth; traversal remains bounded.
3. Distinct calls can share a source line and enclosing function. Impact evidence preserves UTF-16 site columns rather than collapsing them to one file/line record. Context retrieval retains its existing enclosing-symbol deduplication.
4. Canonical target mapping and exact JSON accounting are shared with context retrieval, keeping source-boundary validation and budget accounting in one component each.

## Reproduction and limits

```sh
UV_OFFLINE=1 uv run --no-sync poe format
UV_OFFLINE=1 uv run --no-sync poe type-check
UV_OFFLINE=1 uv run --no-sync poe test test/selene/test_change_inputs.py test/selene/test_change_impact.py test/selene/test_context_bundles.py
UV_OFFLINE=1 python3 security/probes/run_core_tests.py
UV_OFFLINE=1 PYTHONPATH=src python3 research/probes/change_impact.py --output research/change-impact-results.json
```

Set `SELENE_TEST_TYPESCRIPT_LS` to a pre-provisioned TypeScript language-server executable to include that integration case. The test otherwise skips explicitly. The existing isolated MCP probe accepts an immutable image ID, local Docker socket and synthetic fixture directory.

The [usage documentation](../docs/02-usage/076_change_impact.md) defines input limits, target scope, unapplied-diff semantics, declared generation configuration, conservative source validation and output omissions. Proposed code is not typechecked or executed by the tool. Static navigation, schema declarations and filename-based test roles are weaker than runtime evidence; the response therefore remains partial. Source hashes establish checked observations, not atomic filesystem snapshots or cryptographic version attestations from language servers.
