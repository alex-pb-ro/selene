# Recoverable changes verification

The implementation is on local branch `feat/recoverable-edits`, based on change-impact commit `bd1dae3`. It adds `prepare_change`, `apply_change` and `recover_change`. PR publication remains held because the requested main checkout no longer contains the original source.

## Behavior and acceptance evidence

The focused change-plan and change-input selection passed **31 tests** on macOS. The established offline core selection passed **1,089 tests**, with **13 skipped** and **1,253 deselected**, in 160.59 seconds. Formatting and type checks passed. These are the selected core/backend-independent tests, not an all-language-server suite.

| Requirement | Observed evidence |
| --- | --- |
| Source preconditions and stale plans | A changed second file, including with restored timestamps, prevents writes to the first; file outcomes identify the conflict |
| Intended changes and validation | Plans return affected paths, expected/proposed hashes, line spans, staged syntax diagnostics and bounded execution policy; Python syntax errors block apply unless explicitly allowed |
| Unrelated edits and exact text | Uncommitted unrelated content, Unicode, CRLF bytes and existing permission bits survive apply/rollback |
| Permission failure on a later file | Removing second-directory write permission after the first synced file produces an applied/failed result; the prior file can be rolled back |
| Cancellation | Cancellation after the first file stops further work; a fresh service resumes without changing the first file's applied inode again |
| Repeated request IDs | Identical inputs retain the same handle before and after apply; changed inputs with the same ID fail; repeated apply/rollback does not redo the operation |
| Process death | Six cases terminate a child with `os._exit(73)` after a synced file operation, then resume in another process: forward/reverse operations across modification, creation and deletion |
| Later external edits | Rollback refuses to replace a later observed edit to an applied file; original/proposed versions remain available |
| Open old descriptors | Writes through a descriptor opened before exchange remain on the retained inode, appear as a conflict and can be restored when the applied target still matches |
| Scope and storage | Copied-plan replay in a different project, changed parents, hard links, changed snapshots and overlapping service ownership are rejected; private records are excluded from normal Git addition |

The process-death cases cover interruption between writes. They do not simulate hardware power loss or every possible crash boundary.

## Competing write at the exchange boundary

The native [race probe](probes/recoverable_exchange_race.c) interposes the operating-system rename entry point. It writes competing content immediately before the actual exchange, after Selene's prior source checks. This is a controlled timing injection, not a claim about arbitrary concurrent-editor scheduling.

The application returned a conflict, kept the competing content in the displaced inode, retained both immutable snapshots, and restored the competing content during explicit rollback. It also preserved a custom extended attribute. Results and runtime/probe hashes are in [native-recoverable-changes-results.json](native-recoverable-changes-results.json).

The Darwin constants and signatures were checked against the installed Apple SDK `rename.2`, `copyfile.h` and `sys/xattr.h`. Linux's underlying exchange, no-replace and open-descriptor behavior is specified in the primary [Linux rename manual](https://man7.org/linux/man-pages/man2/rename.2.html). The C probe supports the Linux symbol too, but timing injection was executed only on macOS.

## Isolated Linux and actual MCP

[The Linux probe](linux-recoverable-changes-results.json) ran as non-root on synthetic tmpfs files, with Selene's inherited seccomp boundary applied before importing application packages. It verified extended-attribute preservation, retained original/proposed snapshots, a real second-directory permission failure and subsequent recovery.

[The actual MCP probe](isolated-edits-mcp-results.json) exercised the immutable local image over stdio. It advertised **37 tools**, accepted nested proposed-file data, preserved sources during preparation, applied idempotently and rolled back from a newly started container. Project/file identities remained usable across those container instances on the tested shared filesystem. Existing index, context, impact, network-denial, outside-symlink, parent-environment and logging checks also passed.

The explicit change journal retained the source canary under private, Git-excluded `.selene/change-plans`. No canary appeared in other project metadata, client stderr or Docker daemon logs. This distinction is intentional: recovery requires local source retention, while incidental source caches and logs remain disabled in the isolated profile.

The final tested local image is `sha256:0bd0af9111427d2dd6f4a23a6c4b0ddfff7981ba722a16033081f5a89c065efd`. All 53 source/probe hashes in the MCP report and all runtime hashes in the native/Linux reports matched the checkout before the feature commit. No image or source was published. No model API was called.

## Reproduction and limits

Run the affected tests with `uv run --no-sync poe test test/selene/test_recoverable_changes.py test/selene/test_change_inputs.py`, using `PYTHONPATH=src` and temporary `SELENE_HOME`/`UV_CACHE_DIR` paths. `security/probes/run_core_tests.py` contains the established backend-independent selection.

For the macOS race case, compile the C probe with `clang -dynamiclib`, set `DYLD_INSERT_LIBRARIES` to that local library, `DYLD_FORCE_FLAT_NAMESPACE=1` and `SELENE_INJECT_EXCHANGE_RACE=1`, then run `research/probes/recoverable_changes.py --exchange-race`. Without injection, that Python probe verifies metadata and partial permission failure. Run Linux probes in the established isolated image with non-root identity, network disabled, read-only root, writable temporary storage and the inherited kernel boundary. `security/probes/isolated_mcp.py` writes the full stdio result artifact.

The design provides recoverable file operations, not a global filesystem transaction. Native deployment remains unconfined. External readers can observe intermediate project states; writers with open descriptors can continue changing retained inodes; concurrent directory moves and storage power-loss behavior have platform limits. Ambiguous state is retained for manual review. Complete ACL combinations, Windows, other filesystems and every third-party editor were not verified. See the [usage contract](../docs/02-usage/077_recoverable_changes.md) for supported inputs and retention.
