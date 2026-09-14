# Feature completion audit

This audit checks the five requested capabilities and their foundations against the local implementation, executable evidence and repository state. Local implementation is established for the supported contracts; full completion of every research acceptance gate is not established. The machine-readable [audit](feature-completion-audit.json) records branch commits, artifact hashes, runtime versions and PR state.

## Requested capabilities

| Deliverable | Authoritative implementation | Exercised evidence | Remaining scope or limit |
| --- | --- | --- | --- |
| Context bundles | `feat/context-bundles`, `03235a2`; `find_context`, `continue_context`, `read_context_items` | Versioned code/dependency/test/docs/config output, exact budgets, deduplication, continuation replay/expiry, scope and stale-handle tests; actual packaged MCP; comparative Python/TypeScript retrieval | Full enclosing-symbol spans can be omitted; paired agent task outcomes and representative repositories remain unmeasured |
| Change-impact analysis | `feat/change-impact`, `bd1dae3`; `analyze_change` | Real Python alias/call-site and TypeScript interface/implementation tests; local schema/generation evidence; independent broad-versus-selected regression experiment | Dynamic reflection caused a measured missed regression; output is explicitly partial, not complete impact |
| Recoverable multi-file edits | `feat/recoverable-edits`, `d2780f0`; `prepare_change`, `apply_change`, `recover_change` | Source preconditions, second-file permission failure, cancellation, six process-death cases, repeated IDs, preserved timestamps, Unicode/CRLF, retained concurrent edits and restart recovery; native/Linux/actual MCP probes | Per-file recoverability does not provide a globally atomic update; Windows, arbitrary directory races and power-loss behavior are unverified |
| Incremental local index | `feat/incremental-index`, `59d7c3b`; `search_index` and shared synchronization | Native unchanged 10,000-file fast path with zero source opens/directory enumeration, content reconciliation, real Linux queue overflow and immediate host edits through shared-filesystem fallback | Native watcher observations are advisory; unsupported/shared filesystems reconcile; portable Windows fallback lacks equivalent runtime evidence |
| Scoped evidence-backed memory | `feat/evidence-memory`, `23f84ea`; optional provenance, `check_memory`, `review_memory` | Owner/scope/source/body versions, stale/expired/unverified states, explicit review/adoption, storage limits, dashboard behavior and cross-container persistence; 259 affected tests | Owner is declared, semantics are unverified, saves are not compare-and-swap against unrelated editors; no expanded instructions or automatic summaries |

The implementation branches are stacked so each requested feature has its own diff. The acceptance follow-up is a separate test/documentation change above the memory branch. It does not alter runtime behavior or collapse the five feature diffs into one PR.

## Foundations and data boundary

- `fix/task-dispatch` (`6a2d5a2`) replaces polling with signalled FIFO dispatch. The synthetic report measures median no-op dispatch at 0.036 ms versus 104.237 ms before the change. This is local dispatch evidence, not an agent task-success metric.
- `fix/cancellation-ownership` (`54c5a39`) retains execution ownership until work exits, keeps the protocol responsive, propagates cooperative cancellation and avoids replaying uncertain mutations. Existing tests and actual stdio cancellation/timeout/disconnect probes exercise those guarantees. Uncooperative native code retains ownership until it stops; cancellation is not a claim that Python threads were killed.
- `fix/source-freshness` (`748c9e3`) checks content versions and reports conflicting unsaved drafts. Preserved/decreasing timestamps and failed-notification retries are covered. The incremental index later supplies the healthy-watcher fast path while mutation preconditions still use content checks.
- `fix/privacy-boundaries` (`6bfe9b8`) supplies a separate, bounded Linux stdio deployment with one project mount, restricted filesystem/credentials, inherited network denial and suppressed incidental logging/cache persistence. Native Selene remains unconfined. The final memory image's actual MCP probe passes the combined feature and privacy checks with 39 tools and 63 matching runtime/build/probe hashes.

Each feature's usage and verification document describes what remains local, what returns to the connected client and what is retained. Index/context/impact add no model provider or remote service. Recovery journals and authored memories deliberately persist local content; their canaries were absent from unrelated metadata and logs in the tested isolated profile. No arbitrary company identity is inferred from a project path or owner string.

## Evidence quality and unfulfilled research gates

The latest core selection passed 1,116 tests, with 13 skipped and 1,253 language-gated cases deselected, followed by additional focused memory and TypeScript checks. It is not an all-language or all-platform pass. Historical per-feature reports describe their own commits/images; the latest packaged runtime and comparative retrieval reports identify their current source hashes explicitly.

The [comparative context follow-up](context-acceptance-verification.md) supplies fixed-budget symbol-span/file recall, duplicate-range counts, cold/warm timing and four predefined baselines over two authored projects. It also exposes weaker full-symbol coverage in the TypeScript case. That is stronger evidence than the original one-fixture file-recall result, but remains too narrow to establish model task completion.

Still missing from the research evaluation strategy are paired runs with the same model/client/task against native tools, prior Selene and the new features; independently checked task completion and unintended edits; provider-reported tokens; and a representative real-project/backend suite. Those cannot be inferred from green unit tests or faster dispatch. The existing impact experiment measures missed regressions on one synthetic case only. Instruction benefit is not claimed because this work did not expand the instruction templates or generate automatic summaries.

The [agent benchmark preparation](agent-benchmark-preparation-verification.md) now supplies three authored tasks, independent checks, reference repairs, regression mutants and eighteen matched workspaces. All twelve trusted-fixture outcomes and nine result-schema checks behaved as expected. No agent trials ran. Client/provider selection, fresh-session authorization, verified client tool confinement and an isolated submission verifier remain prerequisites; this preparation does not close the missing evaluation gates.

SDK v2/Tasks migration, broad cross-repository graphs, local embeddings, persistent semantic stores and server pools were later roadmap options, not substitutes for the five selected capabilities. They remain outside this implementation. No claim is made that the entire research roadmap is delivered.

## Publication and integration

Read-only inspection found remote `main` at `40e84b84fc22815f6977f0a0110faf688975791f`. It deleted the server source but retains common ancestor `5dc6cbd3ce9d59799774f2a22fe97c846d555196` with the feature branches. The requested local checkout stays unchanged on that main commit.

The original source-base publication hold was broader than necessary: draft PRs can expose the requested diffs without restoring main or resolving its deletions. A draft stack is prepared: the first foundation PR targets main; later PRs target the preceding branch. Source restoration or retargeting must be resolved deliberately before integration. No merge, reset, force-push or source restoration is part of the proposed publication step. Workflow files use manual `workflow_dispatch` triggers; the draft stack does not claim automatic CI results.

Automatic approval review rejected the attempted branch push before execution. Its stated reason was that exporting the non-public implementation and audit source to an external repository lacked explicit authorization for that payload and destination. The user has been asked to approve publication of the implementation, tests and audit artifacts to the public `alex-pb-ro/selene` repository. No branch or PR has been published, and no alternative upload was attempted. This approval is distinct from the later decision about integrating the source deletions on main.

PR URLs and verified branch targets are recorded in the JSON audit after creation. Until those exist, local branches alone do not satisfy the user's separate-PR deliverable. Even after publication, the remaining evaluation limits above must stay visible rather than being presented as achieved acceptance gates.
