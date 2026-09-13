# Incremental local indexing verification

The implementation adds a local lexical index and the optional `search_index` MCP tool, and replaces repeated discovery/hashing in language-server notifications with shared index observations. It retains content reconciliation for event loss, changed inclusion rules, periodic refreshes and unsupported watcher coverage. No model calls, embeddings, remote index or new dependency were introduced.

## Evidence

| Check | Result |
| --- | --- |
| Final focused index, freshness and ignore-parser behaviors | 70 passed, including restored/decreased timestamps, create/rename/delete, ignore reload, scope boundaries and cancellation |
| macOS unchanged-refresh I/O audit | No `open`, `os.scandir` or `os.listdir` calls during a healthy unchanged refresh |
| Existing real Pyright synchronization integration | 10 passed, including reference discovery and changed open-buffer source |
| Repository core selection | 1,026 passed, 13 skipped, 1,248 deselected in 158.14 seconds during implementation; final focused checks cover the subsequent scope/VM-share changes |
| Linux inotify kernel overflow | Actual 16,384-event queue overflow; reconciliation recovered 8,213 expected source files |
| Isolated stdio MCP | Index results contain source hashes; host-created files appear immediately through the VM share |
| Isolated privacy checks | Network creation denied; escaping host symlink unreadable; parent canary environment variable not forwarded; source canaries absent from client stderr, daemon logs and project metadata |
| Formatting and type checks | Passed |

Machine-readable results: [native measurements](incremental-index-results.json), [Linux acceptance](linux-index-results.json), [isolated MCP acceptance](isolated-index-mcp-results.json). Each records source hashes. Historical dispatch/freshness/privacy results remain separate rather than being rewritten as current measurements.

The latest 10,000-file native benchmark measured 0.031 ms median per unchanged notifier poll, versus 378.630 ms in the preceding full-content freshness implementation. Index startup took 2.776 seconds; a changed-file observation took 8.025 ms in this synthetic run. See the JSON for measurements and source hashes. These are single-machine microbenchmarks, not end-to-end model latency or a universal speedup guarantee. Startup, periodic reconciliation, shared filesystems and structural changes still pay for full content scans.

## Findings that changed the implementation

1. An FSEvents probe returned an empty immediate observation after a completed write, then delivered the path later, despite using `FSEventStreamFlushSync`. The runtime implementation uses kernel vnode watches on macOS. The [Apple flush documentation](https://developer.apple.com/documentation/coreservices/1445629-fseventstreamflushsync) describes delivery flushing; the local result did not establish a sufficient boundary for completed file writes.
2. In the isolated Linux image, inotify on `/workspace` initially missed a file created by the host. The mount was virtiofs. Filesystem eligibility now selects content reconciliation there, and the same MCP test passes. Merely opening a watcher is insufficient evidence of cross-VM event coverage.
3. A new in-project symlink needs alias tracking even when it is introduced after the initial scan. Ignored escaping directory aliases must not force reconciliation on every unrelated file edit. Both cases have behavior tests.
4. Ignore parsing previously tolerated unreadable content. Index refresh uses strict parsing and remains retryable after the file is corrected, preventing a parse failure from silently widening retrieval scope.

An overly broad `-m 'not python'` test run was interrupted after selecting unrelated language integrations. It had 502 passes, 15 failures and 9 skips; observed failures included missing Go, Rust, .NET and PowerShell runtimes and Kotlin initialization failure. Those results do not establish compatibility for those backends. The subsequent established core selection passed. No additional language runtimes were installed to hide these limits.

## Reproduction and limits

Use the existing environment without synchronizing dependencies:

```sh
UV_OFFLINE=1 uv run --no-sync poe format
UV_OFFLINE=1 uv run --no-sync poe type-check
UV_OFFLINE=1 uv run --no-sync poe test test/selene/test_local_index.py test/selene/test_file_freshness.py test/selene/util/test_file_system.py -q
UV_OFFLINE=1 uv run --no-sync poe test test/selene/test_ls_file_sync.py -q --timeout=60
UV_OFFLINE=1 python3 security/probes/run_core_tests.py
PYTHONPATH=src python3 research/probes/incremental_index.py
```

The Linux probe is `research/probes/linux_index.py`, run with `python -I -S` inside the built isolated image, with `SELENE_HOME=/tmp/selene-state`, a non-root UID, no-new-privileges, default Docker seccomp, network none, read-only root and writable temporary filesystem. It applies the additional network filter before dependency imports. It creates synthetic files inside `/tmp`, deliberately overflows the native event queue and validates recovery. `security/probes/isolated_mcp.py` tests the actual launcher and host-shared project. Use an explicit local Docker socket and immutable image ID; neither probe uploads project data or calls a model.

The tests establish the stated local behaviors, not an atomic whole-project snapshot, a full packet capture, arbitrary backend compatibility or the AI client's provider contract. Native events are advisory; remote writes, some mapped writes and mount changes can escape event observation. Candidate reads are version-checked and explicit/full reconciliation remains available. Windows and untested filesystems are not claimed as verified.
