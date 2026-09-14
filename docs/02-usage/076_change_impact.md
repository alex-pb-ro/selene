# Proposed-change impact analysis

Enable the optional `analyze_change` tool to inspect a text change before applying it. The isolated stdio profile enables it by default. The tool maps changed lines to existing symbols, follows static references and supported implementation relationships, identifies test candidates, and reports unresolved behavior. It reads the active project and does not apply the proposal, execute project generators or run tests.

Supply either a unified diff against the current source or complete proposed file contents with explicit preconditions:

```json
{
  "changes": [
    {
      "path": "payment_api.py",
      "expected_sha256": "the-current-file-sha256-returned-by-search_index-or-find_context",
      "new_content": "def charge(amount: int, approval: str) -> bool:\n    return bool(approval)\n"
    }
  ],
  "scope": "",
  "max_depth": 2,
  "max_chars": 20000
}
```

A null `expected_sha256` requires a missing path and means creation. A null `new_content` means deletion. Existing sources must be searchable files admitted by the project index. Inputs that target ignored files, external aliases, duplicate canonical paths or stale source versions fail explicitly. Hashes are checked again before returning the report, including edits that preserve timestamps. An existing API can be analyzed before deletion because the language server still sees its current definition and callers.

Unified diffs use exact text context and line coordinates; shifted or mismatching hunks are rejected. The parser supports text modifications, creations, deletions, CRLF source and explicit missing-final-newline markers. Git-style `a/` and `b/` header prefixes are removed as a pair. Binary patches, mode-only changes, copy/rename headers and unsupported quoted paths require a different representation; represent a rename with explicit deletion/creation proposals. The diff must describe an **unapplied** proposal against the current tree. A diff of changes already applied to the working tree generally has a different base and will be rejected.

The report distinguishes:

- `language_server_relationships`: references, implementations and import bindings established through local language-server navigation, with source versions and reference sites. Python renamed imports are traversed explicitly; an alias does not add a caller level. Separate sites on the same line retain their 0-based UTF-16 columns.
- `declared_relationships`: local JSON Schema references and explicit generation mappings. These establish a declared dependency; they do not prove that generated output is current or that a behavior will regress.
- `heuristic_candidates`: matches on changed identifiers, filenames and related words. Test names and dynamic-wiring markers are clues, not execution coverage.
- `uncertainties`: missing semantic support, indexing/query failures, graph and resource limits, dynamic behavior, unverified generation and the absence of proposed-code validation.

`changed_symbols` records how old source ranges map to symbols. Insertions use explicitly approximate adjacent-symbol mapping; new files have no semantic baseline yet. `changes` includes the current and proposed SHA-256 versions. Changed ranges use 0-based half-open line intervals; source references use 1-based inclusive lines. An origin tagged `proposed` belongs to the supplied new file, rather than an existing source snapshot.

`recommended_tests` groups candidate tests by file, preserving the strongest returned evidence and known symbol names. Static references do not prove runtime execution, coverage or test discovery. Use the project's independently configured broader regression suite before release. The [evaluation](../../research/change-impact-verification.md) includes a reflective regression missed by the selected tests.

`scope` limits reported targets to a project-relative file or directory. Changed sources and connecting evidence may lie elsewhere inside the same project; this allows, for example, requesting only test targets for a change in `src/`. Cross-project analysis is unsupported. Context hashes are observations, not an atomic filesystem snapshot or a cryptographic attestation of a language server's answers.

## Schema and generation adapters

The schema adapter reads local `.json` documents containing `$ref`. It compares changed JSON pointers and follows file/pointer references only through admitted project files. Remote references are not fetched. Named anchors, malformed JSON and exhausted adapter limits are reported as unresolved.

For generated artifacts, add a project-root `selene-impact.json` file describing explicit dependencies:

```json
{
  "version": 1,
  "generators": [
    {
      "inputs": ["api/schema.json"],
      "outputs": ["src/generated/client.py", "src/generated/types.py"]
    }
  ]
}
```

The adapter treats this file as data. It reads no commands, expands no shell expressions or globs, and executes no generators. Paths must resolve to indexed local files. A changed input identifies its declared outputs, with the mapping file's version as evidence. Generation freshness remains unverified until the project's approved generation/validation workflow runs. The adapter does not infer a proven generated dependency merely from similar names or a generated-file banner.

## Bounds and deployment

Input is limited to sixteen files, 2 MiB of proposed text per file and 8 MiB total. A unified diff is limited to 8 MiB and 256 hunks per file. Analysis captures at most 64 source files, visits at most 24 graph symbols, retains at most 128 graph findings and performs at most 96 logical semantic operations. Traversal depth is one to four; the default is two. The twenty-second semantic allowance is checked between operations, so a running backend request follows its own timeout and cancellation rules.

The output allowance is 4,096–100,000 Unicode characters for the complete JSON string, including metadata and escaping. It is not a model token count, UTF-8 byte allowance or limit on the enclosing MCP message. Truncation counts omitted findings, uncertainty details and symbol mappings; file-change summaries are retained. There are no impact continuation handles. Narrow the changed-file set, increase the output allowance or inspect returned boundary symbols when coverage is limited.

The result remains `partial`: static navigation and declared mappings cannot establish complete runtime impact. Python/Pyright and a focused TypeScript interface case have been tested; this does not establish equivalent coverage for every language server.

No model, embedding, remote index, remote schema or telemetry service was added. Proposal bodies and analysis state live only for the request. Native launch retains its existing logging and language-server behavior. Use the [isolated deployment profile](073_isolated_stdio.md) for the verified OS/process-tree restrictions; the connected AI client's provider contract remains a client concern.
