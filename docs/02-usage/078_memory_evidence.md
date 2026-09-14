# Memory evidence and review

Project memories can retain a decision together with its declared owner, scope and supporting source versions. Selene checks those versions when reading or assessing the record, and reports when they change. Matching bytes establish source freshness; they do not prove that a decision is correct or that its author has the declared identity.

This is opt-in per record. Existing Markdown memories keep their ordinary read behavior. Add `check_memory` and `review_memory` to `included_optional_tools` to expose explicit assessment and review. They are enabled in the isolated stdio profile and excluded by the `no-memories` mode. `write_memory` accepts optional provenance wherever that tool is already enabled.

## Record a decision

Read the relevant source first. The local index and context tools return source references containing project-relative paths, exact file SHA-256 hashes and line ranges. Supply current references and the decision body to `write_memory`, for example:

```json
{
  "memory_name": "architecture/cache",
  "content": "Keep cache expiry explicit. Review this decision when its supporting configuration changes.",
  "provenance": {
    "owner": "team:application",
    "origin": "decision",
    "scope": "src/cache",
    "evidence": [
      {
        "path": "src/cache/config.py",
        "sha256": "<SHA-256 of the exact current file bytes>",
        "start_line": 1,
        "end_line": 12
      }
    ]
  }
}
```

The hash placeholder must be replaced with the actual digest. Line numbers are one-based and inclusive. An optional `symbol` is a descriptive label, not a separately validated semantic identity. Hashes cover the entire source file, so a change outside the cited range also marks the evidence stale. References must name searchable, canonical sources inside the active project and the declared scope. An empty scope means the whole project.

New provenance records require the memory name to be absent. To upgrade or replace an existing record, pass its current `expected_memory_sha256`, obtained through `check_memory`. This is the hash of the raw memory file, including its provenance comment and exact line endings; it differs from the decision body's hash.

`owner` and `origin` are declarations supplied by the connected client. Origins are `observation`, `decision` and `human_decision`. A human decision may explicitly have an empty evidence array; its status remains `unverified`. No company identity or policy is inferred from the owner label. Optional `expires_at` accepts an ISO timestamp with a timezone.

## Read, assess and review

`read_memory` prefixes an evidenced record with an assessment before returning its body. `check_memory(memory_name)` returns the assessment, current raw-memory hash and declared provenance without the decision body. The dashboard shows the status beside the editable body and submits the version it loaded when saving.

| Status | Meaning |
| --- | --- |
| `current` | The reviewed body and all referenced source versions/ranges still match |
| `stale` | Supporting source changed, disappeared, became excluded or unavailable, or a reference is invalid |
| `needs_review` | The memory body changed after its evidence was recorded |
| `expired` | The recorded expiry time has passed |
| `scope_mismatch` | The record cannot be used with this project binding |
| `unverified` | It is an ordinary memory, a declared decision without source evidence, or validation could not be established |

An assessment can contain several issues; a single displayed status does not hide that issue list. An evidenced body is withheld when its project binding or assessment cannot be established. Ordinary legacy memories are still returned as plain content.

Editing the Markdown body through `edit_memory`, ordinary `write_memory`, reference maintenance or the dashboard preserves the old provenance. It therefore requires review rather than silently updating the supporting hashes. To review a record:

1. Inspect the current decision and its supporting source.
2. Obtain the current raw-memory hash with `check_memory`.
3. Call `review_memory` with `memory_name`, `expected_memory_sha256` and newly supplied `provenance` containing the reviewed source versions.

The review records the current body, owner declaration, evidence and time. Reusing stale source hashes is rejected. A source change that is later reverted to its exact original bytes becomes current again if all other conditions still hold. There is no automatic summary generation or background rewrite of memory files.

## Project boundaries

The binding is a digest of the canonical project root and its filesystem identity. It is stored as a digest, not the absolute root path. An alias of the same root works; another clone, a relocated checkout or a copied record normally requires review. This is a local applicability check, not cryptographic authentication against a person who can edit the raw record.

Copied records are withheld until an explicit `review_memory(..., adopt_project=true)` supplies current evidence for the destination project and the current raw-memory hash. Review the raw local file deliberately before adopting it; normal memory reads do not automatically expose its body. No automatic cross-project or global reuse occurs for records with provenance. Writing or moving them into `global/`, outside the active project or through memory-path symlink aliases is rejected. Existing read-only and ignored-memory rules still apply. Ordinary global memories retain their existing behavior.

## Storage, limits and privacy

Each record is one human-readable `.selene/memories/<name>.md` file. An initial HTML comment contains JSON metadata: format version, project binding, declared owner/origin, scope, source paths/ranges/hashes, decision-body hash, recording time and optional expiry. The following Markdown is the client-authored body. Source bodies are not automatically copied into this metadata; callers should store concise decisions rather than transcripts or credentials.

- One to sixteen source references, except explicitly declared human decisions without source evidence.
- At most 16,000 body characters, subject also to the existing `write_memory` content limit, and a 32 KiB provenance header.
- New or upgraded records are admitted while fewer than 256 evidenced records exist. Admission scans at most 4,096 files. Existing records can still be reviewed or edited at the limit. This is a soft admission check, not an operating-system quota against concurrent external writers.
- Evidenced writes use private `0600` permissions. Records persist until deliberately edited or deleted; expiry changes the assessment and does not delete the file. They remain versionable through the user's normal repository workflow.

The raw-memory hash is an observed write precondition. Each save publishes the body and provenance together through the existing temporary-file and atomic-replacement helper. This does not lock unrelated editors or provide an atomic compare-and-swap against a writer changing the file after the check. Memory saves do not use the multi-file recovery journal and retain no automatic prior-version history. Source assessments are observations, not locks preventing changes after the result is returned.

All evidence checks use local files and the local index. Selene makes no model request, embedding request, telemetry call or external evidence fetch for this feature. Requested memory results return to the connected MCP client, whose existing provider and data-handling arrangements remain its responsibility. No new destination is introduced. Native logs and backend permissions remain subject to the [privacy audit](070_security.md); the [isolated profile](073_isolated_stdio.md) disables incidental application/daemon logging and retains only the explicitly authored project memory and recovery records.

Prompt templates and onboarding summaries are unchanged. This feature supplies reviewable records and observable staleness; it does not claim measured improvement in agent task success or semantic correctness. See the [verification report](../../research/memory-evidence-verification.md) for exercised cases and limitations.
