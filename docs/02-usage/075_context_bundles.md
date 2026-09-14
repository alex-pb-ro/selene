# Context bundles

Enable the optional `find_context`, `continue_context` and `read_context_items` tools in `included_optional_tools`. The isolated stdio profile enables them by default. Context retrieval runs locally and uses the existing lexical index and active language servers. Results go through the connected MCP client; there are no added model calls, embeddings or remote index services.

```json
{
  "query": "checkout payment approval",
  "anchors": [{"path": "checkout.py", "symbol": "checkout"}],
  "scope": "",
  "max_chars": 20000,
  "include_bodies": true
}
```

`anchors` accepts up to eight relative paths, each with an optional symbol name path such as `Payment/capture`. Explicit anchors precede lexical matches. The service expands a bounded set of language-server definitions and references, then adds tests, documentation and configuration using identifier overlap. Names and filename conventions are heuristics; the response preserves this distinction in each item's evidence. A static reference does not establish runtime execution or complete change impact.

Each item has a stable ID within the bundle, a project-relative source path, canonical in-project path, SHA-256 content version, inclusive 1-based start/end lines, retrieval roles and selection evidence. Semantic edges include the originating symbol and reference-site source version. Overlapping ranges are deduplicated. Supporting files outside the requested scope, excluded paths and aliases to ignored or external targets are omitted.

`max_chars` is an exact allowance of 2,048–100,000 Unicode characters for the returned JSON string, including metadata and JSON escaping. It is not a model token count, UTF-8 byte count or allowance for the enclosing MCP message. The `budget.used` value equals the string's length. Metadata that cannot fit produces an actionable error asking for a larger allowance. This explicit allowance takes precedence over the legacy default response limit for these tools.

Bodies are excerpts, limited to 40 lines on context pages and 500 lines when selecting bodies. `body_status` is `omitted`, `partial` or `complete`, and `shown_end_line` identifies the last included line. Long individual lines may not fit at all. For longer source ranges use the existing file-reading tools; context continuation pages advance through items, not through the remaining lines of a partial body.

Deduplication may retain a method's more specific range when it overlaps an enclosing type. `complete` describes the selected range, not the whole class, interface or file. If the enclosing declaration is needed, request it as an explicit symbol anchor in another `find_context` call. The [comparative retrieval check](../../research/context-acceptance-verification.md) measures this distinction separately from file coverage.

To continue, pass the returned `continuation` to `continue_context`. To fetch chosen bodies, pass `bundle_id` and one to sixteen distinct `item_ids` to `read_context_items`. Continuations can be replayed while the selection remains valid. Plans expire five minutes after creation, and each project retains at most eight plans in memory. IDs are valid only in the service instance that created them. Source bodies are reread for each request; the service retains only bounded selection and version metadata between requests.

Selections reject changed index generations, changed source hashes, changed canonical targets and newly excluded sources. This is conservative: an unrelated indexed file change can also require a new `find_context` call. Participating source hashes are checked directly before returning a page, including changes with restored timestamps. A replaced project root requires reactivation. Checks are observations, not a globally atomic snapshot; files can change after a response, and the language server does not provide a cryptographic version attestation for its semantic answers.

Coverage is deliberately explicit. Selection reads at most 48 searchable files, retains at most 64 candidates, expands at most six symbols over two dependency hops, and performs at most 40 logical semantic operations. The ten-second semantic allowance is checked between operations; startup, filesystem synchronization and an already-running backend request follow their own timeouts. Source files above the index's 2 MiB searchable-text limit are excluded. Filename classification, unsupported backends, failed operations, resource limits and scope issues are surfaced as limitations. When no language server is available, lexical retrieval still works with that limitation marked.

See [the isolated deployment profile](073_isolated_stdio.md) for OS-enforced privacy boundaries. Native deployment retains its existing logging, language-server behavior and client configuration; these tools do not confine arbitrary native processes or determine the AI client's provider contract.
