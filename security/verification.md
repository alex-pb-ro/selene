# Verification record

Verified on macOS/Apple Silicon with Python 3.11.15, using the pinned development environment. Public packages were downloaded for installation/testing; no private project data was used in the network probes.

| Check | Result and scope |
| --- | --- |
| Core test suite | **981 passed, 11 skipped, 1,242 deselected**. All tests without language-integration markers were selected, including the four new privacy regression tests. Platform-dependent cases were skipped. |
| Formatting/lint and type checks | `uv run --no-sync poe lint` and `uv run --no-sync poe type-check`; both source and test typing checked. |
| Python language-server health check | Passed on the bundled fixture after cache hardening: symbol overview/search and nine references to `UserService`. |
| Real MCP stdio session | Server identifies as `Selene`, version `1.7.1.dev0`; 29 tools discovered; initial instructions returned successfully and contain the privacy rule. |
| Dashboard browser | Fresh headless Chrome, synthetic data; overview/logs/statistics exercised; four Chart.js charts; **zero external requests and zero browser errors**. See `browser-verification.json` and `dashboard-verification.png`. |
| Startup without network | Python DNS/connect hooks reject and record attempts during headless agent creation, initial instructions, local statistics and dashboard asset/API requests; none occurred. |
| Local HTTP privacy | Real loopback proxy/destination/redirect test confirms that environment proxies are bypassed and redirected project requests are refused before reaching the target. |
| Cache safety | Normal symbol values survive round trips; an executable pickle attempting a file write is rejected before execution. |
| PHP/JSON/YAML/Solidity processes | Actual pinned Node servers initialize and enumerate symbols from synthetic documents. JSON/YAML contain canary remote-schema URLs. PHP/JSON/YAML make no recorded network attempts; Solidity makes the two public-metadata requests disclosed in the audit, rejected by the probe. No Application Insights/Sentry events observed. The probe deliberately returns nonzero for **any** network attempt, including those known metadata requests. |
| Optional Agno application | ASGI lifespan/config endpoint works with sockets blocked; both telemetry flags and tracing are false even when the parent environment opts in. External API docs disabled. No model call was made. See `agno-verification.json`. |
| Docs | Full Sphinx build with warnings treated as errors passes. Generated-page resource scan finds no external script/style/image/frame URLs. MathJax is served locally. |
| Packaging | Source distribution and wheel build. Wheel inspected for renamed entrypoints/modules and bundled dashboard scripts/privacy helpers. No old-name package paths; the extracted wheel CLI also imports and runs independently of the checkout source. |
| Prompt/memory integrity | Prompt factory regenerated; project memories checked after registering the checkout in a temporary Selene home; no referential-integrity issues. |
| Naming and licensing | Repository name scan finds the former name only in the one README attribution sentence/link. MIT license bytes preserved. Git history is retained; no Git remote is configured. |

## Reproduce

From the checkout, install `uv sync --locked --all-extras`. For core tests, run:

```sh
uv run --no-sync python security/probes/run_core_tests.py
```

This script derives the language-marker exclusion expression from `pyproject.toml`, applies a 90-second per-test timeout, and writes its full output to `/tmp/selene-unit.log`. An initial 60-second test timeout was shorter than Pyright's existing 60-second empty-project readiness fallback; rerunning with 90 seconds resolved those two timeouts. One rename-related glob test expectation was corrected. An initial attempt to run every language integration test was stopped because the many external toolchains are not installed; the successful core selection does not claim coverage of all languages.

```sh
uv run --no-sync poe lint
uv run --no-sync poe type-check
uv run --no-sync poe doc-build
uv run --no-sync selene project health-check test/resources/repos/python/test_repo
uv run --no-sync python security/probes/mcp_check.py
uv run --no-sync python security/probes/agno_check.py
uv build --out-dir /tmp/selene-dist
```

The probes use temporary Selene homes and synthetic fixtures. The browser probe needs `playwright-core` and a Chrome/Chromium executable. Start `security/probes/dashboard_server.py` in a separate terminal, then run:

```sh
node security/probes/browser-check.cjs /absolute/path/to/playwright-core /absolute/path/to/chrome
```

For the language-server probe, install the four reviewed versions in a temporary directory, then pass its node_modules directory and Node executable:

```sh
npm install --prefix /tmp/selene-lsp-packages --ignore-scripts --no-audit --no-fund \
  intelephense@1.14.4 yaml-language-server@1.19.2 \
  vscode-json-languageserver@1.3.4 @nomicfoundation/solidity-language-server@0.8.4
uv run --no-sync python security/probes/lsp_privacy.py \
  /tmp/selene-lsp-packages/node_modules /absolute/path/to/node
```

Node instrumentation records and rejects HTTP, HTTPS, TCP, TLS, DNS and fetch calls during initialization, document opening/symbol retrieval, and a 22-second observation window. It is **not an operating-system egress sandbox or packet capture**. A separate process or native module can bypass these hooks. All four symbol operations passed even with the two Solidity metadata calls blocked.

Docker, Nix, Windows/Linux wheels, proprietary IDE plugins, and the complete cross-language integration matrix were source-reviewed where present but not executed. No external model inference, license activation, hosted CI, or publication was performed. Provider-side behavior and arbitrary custom programs remain outside these checks.

## Follow-up data-use audit

The stricter provider-only assessment is in [DATA_FLOW_AUDIT.md](/Users/alexp/workspace/side/local-ai-marketplace/selene/DATA_FLOW_AUDIT.md). All 1,047 source-inventory hashes still matched; this follow-up changed no runtime files. It added these observations using synthetic data:

- `data-use-verification.json`: real MCP calls read a gitignored `.env` and an outside-file symlink, while direct parent traversal was blocked. Contents were copied into disk/stderr logs. Deleting a memory left its contents in logs. Global memories were shared across project managers. A dashboard log could be read without a token; an unrelated Host header was rejected. A managed child inherited a fake environment value, and the shell helper sent that value to an audit-owned loopback service.
- `cache-data-verification.json`: real Pyright 1.1.403 persisted a synthetic comment outside the returned symbol body in the source cache. It remained immediately after source deletion. No network attempts were recorded by the Node instrumentation.

The observed log, memory and cache file modes were `0644` under umask `022`; this does not override parent-directory restrictions or demonstrate another user accessing the private audit directory. No real project data or real credentials were sent to a receiver. These probes document current behavior; their successful completion is not a privacy-policy pass.

```sh
uv run --no-sync python security/probes/data_use_audit.py
uv run --no-sync python security/probes/cache_data_audit.py \
  /absolute/path/to/node /absolute/path/to/pyright/dist/langserver.index.js
```

Use an already installed Pyright 1.1.403. The data-use probe requires a loopback listener. The earlier core suite was not repeated for these audit-only artifacts.
