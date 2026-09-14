# Incremental local code and documentation search

Selene maintains a project-owned index of source files and documentation. It uses local word and identifier matching; it does not call an embedding service, model API, analytics endpoint or external index. Fingerprints, paths and lexical postings stay in process memory. Search results are returned through the connected MCP client.

## Search

Enable the optional `search_index` tool in your Selene configuration:

```yaml
included_optional_tools:
  - search_index
```

The isolated stdio profile enables it automatically. Example arguments:

```json
{"query":"capture payment", "relative_path":"src", "limit":10}
```

Matches include project-relative paths, SHA-256 fingerprints of physical file bytes, matched terms and up to three source lines. Line numbers are **1-based**, unlike the 0-based editing tools. Matching is case-insensitive and splits identifiers such as `capturePayment` and `capture_payment`. Files matching more query terms rank first, followed by path matches and a deterministic path ordering. Results can match some of the query terms; this is lexical retrieval, not a claim of semantic relevance or exhaustive change impact.

The result includes an index generation, observation/reconciliation times, watcher mode, file counts and scope issues. `ready` means the observed event queue was drained; it does not describe an atomic snapshot of the whole project. Each returned candidate is re-read and checked against its indexed content hash. Repeated concurrent changes raise an error instead of returning a supposedly current result.

Use `reconcile: true` to refresh every included file before searching. This is useful after writes that may not generate filesystem events. `max_answer_chars` applies the normal tool response limit.

## Freshness and resource behavior

On eligible local filesystems, Linux uses inotify and macOS uses vnode watches through kqueue. A healthy unchanged refresh does not enumerate directories or open source files. Changed files are re-read and rehashed even when modification times are preserved or move backwards. Language-server file-change notifications share these observations.

Startup, directory/inode changes, ignore-rule changes, event loss and periodic reconciliation rebuild the observation. Included aliases currently trigger full reconciliation when changes arrive; ignored aliases do not. Pending events are acknowledged only after a successful commit; cancellation and read failures cannot silently discard them. Reconciliation runs on the next request after 60 seconds have elapsed, rather than on a background timer. A live index is closed when its project shuts down.

The index conservatively uses content reconciliation for shared or unknown filesystems, including the tested virtiofs VM share. A successful inotify registration on a VM share does not prove that edits made on the host will emit guest events. Resource exhaustion or a failed watcher also selects reconciliation; restarting/reactivating the project retries native setup. macOS watches retain one descriptor per selected file/directory and do not raise the process descriptor limit.

Native events remain advisory. In particular, Linux does not report every `mmap` modification or remote filesystem write. Changing mounts or unsupported write mechanisms can escape event observation until reconciliation. Returned candidates are still checked directly, while `reconcile: true` is available when the complete candidate set must be refreshed. See the [Linux inotify limitations](https://man7.org/linux/man-pages/man7/inotify.7.html) and [Apple vnode event API](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kqueue.2.html).

## Scope and limits

The index excludes `.git`, `.selene`, configured ignored paths and files excluded by project ignore rules. `.gitignore` and `.git/info/exclude` changes refresh the filters. Unreadable/invalid ignore content blocks the refresh until corrected. In-project symlinks are supported, ignored targets cannot be reintroduced through aliases, escaping links are excluded, and directory cycles are reported. Replacing the registered project root requires reactivation.

Text search covers files up to 2 MiB decoded using the project's configured encoding. Files containing NUL bytes or undecodable content are not searched. Oversized and non-text source files still have streaming content fingerprints for language-server notifications. File counts distinguish all indexed files from searchable text files. The index does not retain complete source bodies.

This component does not create an OS security boundary. Use the [isolated stdio profile](073_isolated_stdio.md) when Selene and its children must be prevented from transmitting project data independently. The client controls its AI provider and processing terms.

APFS on macOS ARM64 and tmpfs in the isolated Linux ARM64 image were exercised directly; the VM share was verified using reconciliation. Other eligible local filesystem types, Windows fallback and other language-server integrations remain unverified. Measurements and acceptance evidence are in [the verification report](../../research/incremental-index-verification.md).
