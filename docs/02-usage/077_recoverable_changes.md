# Recoverable multi-file changes

Enable the optional `prepare_change`, `apply_change` and `recover_change` tools to coordinate text changes with local recovery. They use the connected client's existing authorization. Preparing a plan writes its recovery records but leaves the proposed source files unchanged; applying it changes files one at a time.

```json
{
  "request_id": "client-migration-001",
  "changes": [
    {
      "path": "src/example.py",
      "expected_sha256": "<SHA-256 of the exact current bytes>",
      "new_content": "value = 2\r\n"
    },
    {"path": "src/new.py", "expected_sha256": null, "new_content": "created = True\n"}
  ]
}
```

Pass this to `prepare_change`. A null expected hash requires an absent path. A null `new_content` deletes an existing file. Alternatively, supply an unapplied unified `diff` matching current source. Changes use the project's encoding, preserve supplied line endings and avoid converting Unicode character positions into byte offsets. Diff coordinates describe lines; structured changes replace the complete file.

The response includes a `plan_id`, affected paths, expected/proposed hashes, changed line spans, syntax diagnostics and an execution policy. Reuse a request ID only with identical inputs: retries return the existing plan, including after apply. A different proposal with the same ID is rejected. Keep the exact plan ID; its digest binds the immutable manifest to the caller's handle.

Call `apply_change(plan_id)` to apply or resume it. Each file reports `pending`, `applied`, `conflict`, `failed` or `rolled_back`, with observed source and retained-slot hashes. The overall result can be partial. A conflict on any participant detected before forward application prevents all remaining writes. An error after one file changes stops the operation and retains recovery data; automatic rollback does not run.

Use `recover_change(plan_id, action="inspect")` after cancellation, an uncertain response or a server restart. To undo applied files, use `action="rollback"`; this visits them in reverse order and stops on a conflict. Retrying either direction reconciles observed files rather than blindly repeating an operation. Forward application does not restart a rolled-back plan; prepare a new plan for further changes.

## Checks and limits

- One to sixteen text files, at most 2 MiB each and 8 MiB of proposed content. Metadata is limited to 256 KiB. More than 128 disjoint changed ranges in a file are summarized as its whole-file span; exact proposed contents remain in the journal.
- Existing parent directories, canonical project paths, the same filesystem, and regular files without hard-link aliases are required. Symlink traversal, directory operations, binary changes and resource moves are unsupported. Express a supported file move as an explicit creation and deletion.
- Replacements copy existing owner, group, permission, ACL and extended-attribute metadata when staging. New files start with private `0600` permissions. The current source bytes, inode identity, basic permissions and parent identity are rechecked; this is not a transaction over every concurrent metadata operation.
- Python proposals are parsed using the running Python interpreter's syntax; JSON proposals are parsed locally. Other syntax is explicitly `not_checked`. Checks execute no proposed code, generator, build or test command. Errors prevent apply unless the client explicitly prepares with `allow_syntax_errors=true`. These checks predict syntax issues, not cross-file type errors or runtime failures.
- Up to 64 plan or interrupted-preparation directories may be retained. Reaching this limit stops new preparations until completed records are reviewed and removed. Retrying an already-published plan does not consume another slot.

## Recovery and concurrency

On Linux, the implementation uses `renameat2` with exchange or no-replace semantics. Darwin uses `renameatx_np` with the corresponding flags. An unsupported platform or filesystem fails explicitly. Existing files are exchanged with staged files, retaining the displaced inode; creations and deletions move into an absent destination. The Linux API's guarantees and its open-descriptor caveat are documented in the [Linux rename manual](https://man7.org/linux/man-pages/man2/rename.2.html).

The journal publishes complete intent records before changing a source name and syncs file and directory writes. Recovery checks actual inode placement and content, including when the process exited before returning a result. This supplies per-file recovery, not a globally atomic project update. External readers can see intermediate states. Hardware power-loss behavior depends on the filesystem and storage stack.

A later observed edit to an applied file prevents rollback from replacing it. A writer holding an old descriptor can continue editing the displaced inode: that content is retained, reported as a conflict, and may be restored by an explicit rollback when the applied target still matches. No protocol here locks arbitrary external editors or provides a linearizable transaction against concurrent directory moves. Unknown or ambiguous state requires manual review of the retained versions.

## Local data and retention

Plans persist under `.selene/change-plans/<request-digest>/`. They contain original and proposed source bodies, displaced files, hashes, paths, diagnostics and operation intents. The directory is private (`0700`) and contains its own `*` Git exclusion. The local index excludes this metadata. This is explicit recovery storage; it is not a telemetry endpoint or an AI service.

`old-N` and `new-N` contain immutable captured/proposed bytes. `slot-N` retains the currently displaced inode or the staged replacement. `manifest.json` maps entry numbers to paths and expected versions. Intent JSON records the operation's before-state. Interrupted preparations and incomplete unpublished records remain available for inspection. Do not edit records in place to force replay: changed snapshots or manifest digests are rejected, and ambiguous intents must be reviewed manually.

After reviewing a completed application or rollback, remove its whole plan directory if its local recovery data is no longer needed. Do not remove records for a running or unresolved operation. There is no automatic expiry that deletes the only retained copy of conflicting content. Existing native logs/backend behavior remains subject to the [privacy audit](070_security.md); the [isolated stdio profile](073_isolated_stdio.md) disables application and daemon logging and keeps the explicit journal in the authorized project mount.
