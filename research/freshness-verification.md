# Source freshness verification

The change on `fix/source-freshness` is based on `54c5a39` in the recovered source checkout. It covers content observation, open-buffer refresh and retryable language-server notification delivery. It does not implement incremental indexing or a globally atomic filesystem snapshot.

## Behavioral checks

- Focused snapshot/notifier/buffer and decoding selection: **23 passed, 1 skipped**.
- Real cached Pyright integration selection: **10 passed, 1 skipped**, in 20.53 seconds. This exercises new and deleted callers, same-size caller renames with preserved/decreased modification times, tool and low-level reference searches, and symbol positions in an already-open document.
- Unmarked core regression selection: **1,011 passed, 11 skipped, 1,248 deselected**, in 157.13 seconds. This selection does not run all language integrations.
- Repository formatting, type checks and `git diff --check` pass.

The exact preserved-timestamp open-document test was copied to a separate checkout at the unchanged parent `54c5a39`. It failed as expected: after five lines were inserted, the symbol remained reported at line 15 instead of line 20. The same test passes with this change. The parent checkout was not modified except for the regression test and a virtual-environment symlink.

The focused tests also cover failed/ambiguous notification delivery followed by a content reversion, failed creation followed by deletion, per-server retry state, ordered concurrent polls, unreadable files, atomic file replacement, unsaved-buffer conflicts and recovery, no-op drafts, monotonically increasing notification versions and rejecting FIFOs without waiting for a writer. The tests assert externally visible results, files and protocol messages.

## Cost of content verification

`research/probes/freshness.py` reuses only the freshness workload from the historical baseline, leaving `optimization-baseline.json` unchanged. Ten sequential warm samples on macOS 26.6 ARM64 / Python 3.11.15 produced:

| Source files | Median unchanged-project poll |
| ---: | ---: |
| 100 | 3.231 ms |
| 1,000 | 33.281 ms |
| 10,000 | 378.630 ms |

The historical 10,000-file result was 175.366 ms with timestamp-only checks; it missed preserved/decreasing timestamps. Full content verification costs about 2.16 times as much in this synthetic workload. This is an explicit regression in unchanged-project polling latency, retained for correctness pending the separate incremental-index implementation. Both timestamp edge cases now produce a change event. The new result JSON records source hashes and measurement limits.

## Reproduction

Use the existing locked environment without updating dependencies. From the checkout, set `PYTHONPATH` to its `src` directory, `UV_CACHE_DIR` and `SELENE_HOME` to task-specific temporary directories, and `UV_OFFLINE=1`. Then run:

```sh
uv run --no-sync poe format
uv run --no-sync poe type-check
uv run --no-sync poe test -k 'test_file_freshness or test_ls_utils' -q --tb=short --timeout=10
uv run --no-sync poe test -k 'test_ls_file_sync' -q --tb=short --timeout=60
python3 security/probes/run_core_tests.py
uv run --no-sync python research/probes/freshness.py
```

The integration/core selections require local loopback fixtures and a cached Pyright runtime. They were run with the host sandbox escalation granted and package downloads disabled. No model API was called. This is functional verification, not a complete packet capture or proof of child-process egress confinement. Other language servers and operating systems have not been exercised by this change.
