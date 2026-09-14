# Context bundle verification

The optional `find_context`, `continue_context` and `read_context_items` tools combine local lexical retrieval with bounded language-server definitions and references. They return source versions, role and relationship evidence, explicit coverage limits, exact JSON character usage and expiring project-bound handles. The implementation reuses the local index and existing symbol operations; it does not create another semantic index or call an AI provider.

## Checks

| Check | Evidence |
| --- | --- |
| Versioned lexical context, role diversity, exact escaped/Unicode JSON budget, pagination replay, body reads, changed content and ignore rules, aliases, cancellation, expiration and MCP argument validation | 13 behavior tests passed |
| Final context and existing synchronization/manager selection | 26 passed in 25.71 seconds, including two real Pyright context cases with direct and aliased project roots and discovery of a newly created caller |
| Core selection during implementation | 1,049 passed, 13 skipped, 1,249 deselected in 157.30 seconds; the later canonical-path fixes were covered by the final 26-test selection and rebuilt-image probe |
| Actual isolated stdio MCP | 33 advertised tools; nested anchor input, exact budget, selected bodies, continuation pages and rejection after an index generation change passed |
| Existing isolation acceptance | Managed shell network creation denied; external host symlink unreadable; parent secret not forwarded; source canaries absent from client stderr, Docker logs and project metadata |
| Formatting, type checks and patch whitespace | Passed |

The final packaged image is `sha256:599b82e8a08350dbc7e06a65f7366d74250f049f042e660f134ab8c829bfbde0`. The [isolated MCP result](isolated-context-mcp-results.json) checks actual runtime file hashes against the checkout. The image stays in the dedicated local audit VM; it was not published. Only synthetic files were shared with that VM.

## Retrieval experiment and its limits

The [reproducible probe](probes/context_bundles.py) constructs an aliased payment-policy import, data type, calling test, documentation and configuration, plus 40 similarly named distractors. Both methods receive the explicit entry-point file and the same query, and use the same page serializer under a 15,000-character allowance. The baseline selects the anchor plus the top twelve local lexical matches, returning their first thirteen lines.

The final [result](context-bundle-results.json) reports:

| Method | Expected source files returned | JSON characters | Overlapping ranges | Observed retrieval time |
| --- | --- | --- | --- | --- |
| Anchored lexical baseline | 3 of 6 | 5,985 | 0 | 5.533 ms |
| Context bundle | 6 of 6 | 10,691 | 0 | 2,217.715 ms |

The context request used 30 logical semantic operations. The first semantic request includes the backend's initial cross-file reference wait; this is not a warmed steady-state latency measurement. Both payloads fit the same maximum, but they are not equal-sized. The baseline also has a twelve-match cap. These observations establish behavior on one synthetic fixture, not superior agent task outcomes, symbol-level recall, optimal ranking or performance across repositories. No paired model evaluation, grep workflow or repository-map comparison was performed. Python/Pyright was tested; TypeScript and other semantic backends remain unverified for this feature.

The experiment exposed a real path-identity problem: a language-server location could use the canonical filesystem path while the configured project root used an alias. The initial implementation omitted local policy/type targets, and an additional regression showed empty references when root and workspace URIs disagreed. Backend startup now uses the canonical project root, and context locations are mapped only to canonical paths already admitted by the project index. This preserves excluded/external-target protection. The [initial experiment](context-bundle-before-alias-fix-results.json) and [earlier image result](isolated-context-before-alias-fix-mcp-results.json) are historical observations whose hashes intentionally differ from the final runtime.

## Reproduction

Use an existing environment with cached Pyright; these commands do not synchronize project dependencies:

```sh
UV_OFFLINE=1 uv run --no-sync poe format
UV_OFFLINE=1 uv run --no-sync poe type-check
UV_OFFLINE=1 uv run --no-sync poe test test/selene/test_context_bundles.py test/selene/test_ls_file_sync.py test/selene/test_ls_manager.py
UV_OFFLINE=1 python3 security/probes/run_core_tests.py
UV_OFFLINE=1 PYTHONPATH=src python3 research/probes/context_bundles.py --output research/context-bundle-results.json
```

The existing `security/probes/isolated_mcp.py` also exercises the new tools. Run it with the isolated image, an explicit local Docker socket and a synthetic fixture directory. See [usage and coverage](../docs/02-usage/075_context_bundles.md) for body limits, conservative stale detection, native logging behavior and the distinction between observed freshness and atomic snapshots.
