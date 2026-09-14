# Selene capability and optimization roadmap

## Recommendation

Selene's strongest next step is to combine its existing semantic tools into a local system that assembles relevant context, explains the impact of a change, and applies verifiable edits. The highest-value outcome is an agent that reaches the right files faster, understands the consequences of an edit, and can prove what it changed. A larger catalog of independent tools is a weaker objective.

Three capabilities deserve particular attention: **context bundles tied to source versions**, **change-impact analysis that connects code to tests and interfaces**, and **recoverable multi-file changes with explicit preconditions**. These can substantially extend the existing MCP toolkit while leaving reasoning and model calls with the approved AI client. Their expected benefits remain hypotheses until tested against representative coding tasks.

The foundation needs work first. Measurements of the current checkout found approximately 104 ms median overhead for a trivial queued operation and 175 ms for polling an unchanged 10,000-file synthetic project. Separate behavioral checks confirmed that a timed-out operation can overlap its successor and that the file-change notifier misses changes with preserved or decreasing modification times. These are concrete priorities for speed and correctness, alongside the existing privacy findings.

The recommended sequence is: establish privacy and execution boundaries; fix scheduling and freshness; introduce typed, versioned results; build context and impact capabilities; then extend language coverage and client integration using measured evidence. A focused Python/TypeScript implementation should establish the contracts before attempting uniform sophistication across every supported language.

## Current foundation

The checkout is a Python MCP server, rather than a complete client-specific plugin bundle. It already provides semantic navigation, file and symbol editing, memories, multiple client contexts, local usage statistics, and language-server/JetBrains backends. The repository includes no top-level Codex or Claude plugin manifest in the inspected state. Packaging a client wrapper could improve installation, but it would not by itself improve coding intelligence.

| Area | Already implemented | Useful extension |
| --- | --- | --- |
| Navigation | Symbol overviews, definitions, references, implementations and diagnostics | Ranked combinations of symbols, dependencies, relevant tests and documentation |
| Editing | Symbol replacement/insertion, rename, multi-file text replacement | A common change-plan abstraction with file-version checks and recovery |
| Multi-file replacement | Dry-run diffs, expected counts and content-derived occurrence IDs | Extend these safeguards across semantic edits and define partial-failure behavior |
| Response size | Character limits and some progressively shortened responses | Typed pagination, stable continuation handles and explicit completeness information |
| Client fit | Context-specific tool exclusions; IDE single-project mode | Tested capability profiles, smaller descriptions and stable catalogs |
| Language services | Multiple adapters; servers already start in parallel | Lazy startup where appropriate, bounded warm pools and capability-specific health reporting |
| Search | Pattern matching already parallelizes file processing through joblib threads | Workload-aware worker limits, indexed lexical retrieval and selective semantic expansion |
| Persistence | Symbol caches and Markdown memories | Bounded, private, versioned storage with provenance and deletion semantics |
| Advanced refactoring | Additional move/inline/hierarchy/inspection tools through JetBrains | Explicit backend capability reporting and selected portable equivalents |

The distinction matters: “add parallel startup,” “add dry-run replacement,” and “support structured output” would each overlook existing functionality. Improvements should deepen these mechanisms rather than build competing implementations. Relevant evidence is in [language-server management](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/ls_manager.py:100), [multi-file replacement](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/tools/file_tools.py:217), [response shortening](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/tools/tools_base.py:281), [MCP result/schema handling](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/mcp.py:52), and [threaded pattern search](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/util/text_utils.py:296).

## Measured opportunities

The following measurements are from macOS 26.6 on Apple Silicon, Python 3.11.15, using synthetic files and the installed environment. They are local microbenchmarks, not agent task-success or model-cost measurements. The source files were not optimized before measurement. [Baseline data](/Users/alexp/workspace/side/local-ai-marketplace/selene/research/optimization-baseline.json)

| Operation | Samples | Median | Sample p95 | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Sequential no-op through `TaskExecutor` | 30 | 104.237 ms | 105.390 ms | Idle queue polling adds measurable dispatch latency |
| Empty `list_memories` over MCP, desktop context | 12 | 106.797 ms | 107.953 ms | A real trivial tool call exhibits a similar latency floor |
| Poll unchanged project, 100 source files | 10 | 1.555 ms | 1.846 ms | Small projects conceal the scan cost |
| Poll unchanged project, 1,000 source files | 10 | 18.882 ms | 19.539 ms | Work grows with project size |
| Poll unchanged project, 10,000 source files | 10 | 175.366 ms | 177.465 ms | Repeated full walks can materially affect navigation |

The executor checks an empty queue and sleeps for 0.1 seconds. Replacing polling with a condition or blocking queue should remove that component of idle latency. This does not establish a 100× improvement in coding speed: model inference, language-server work, tests and filesystem behavior may dominate real sessions. The smallest observed dispatch was 0.178 ms, illustrating that this overhead depends on timing relative to the poll. [Executor](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/task_executor.py:125)

Client contexts already reduce schema payloads:

| Context | Tools exposed | Serialized catalog bytes | Reduction from desktop |
| --- | ---: | ---: | ---: |
| `desktop-app` | 29 | 37,204 | — |
| `ide` | 22 | 30,469 | 18.1% |
| `codex` | 23 | 29,651 | 20.3% |

These catalogs were measured on a project configured with no language servers. Results can vary with project/backend/tool configuration. Bytes are not tokenizer counts, and actual model context depends on the host's representation, caching and tool discovery. Startup was approximately 0.52–0.62 seconds, measured once per context without language-server startup; it is not a reliable estimate for a real repository's cold start.

Two correctness experiments are more significant than the timing results. A real executor advanced to another task while the timed-out operation remained active; cancelling its future also did not stop a subsequently released in-memory side effect. The real filesystem notifier produced zero events after source content changed while its mtime was preserved or reduced. The latter test did not run a language server: a backend's own watcher may independently notice the change. [Behavioral evidence](/Users/alexp/workspace/side/local-ai-marketplace/selene/research/optimization-baseline.json)

## Research implications

Interface design is a credible way to improve coding agents. SWE-agent studied how the agent-computer interface affects repository navigation, editing and execution. It supports investing in useful tool semantics and feedback; its 2024 task scores do not predict a benefit for current models or for Selene specifically.[^1]

Retrieval should be selective. Repoformer found that unnecessary retrieved context can be unhelpful and studied a learned decision about when to retrieve. CodeRAG subsequently investigated query construction, multiple retrieval paths and reranking. Both concern repository-level code completion, so applying their findings to interactive maintenance is an architectural hypothesis requiring its own evaluation.[^2][^4]

Aider demonstrates a practical alternative to indiscriminate source dumping: its repository map uses a dependency graph to select relevant definitions within a context budget. SCIP provides a language-independent representation for indexed definitions, references and implementations, while Tree-sitter supplies incremental syntax parsing. These are complementary building blocks with different accuracy and freshness properties.[^3][^5][^6]

Tool discovery and bounded composition also have credible precedents. Anthropic describes loading tools on demand and executing/filtering intermediate operations before returning data to a model. Its reported savings concern its own workloads and platform; they must not be projected onto Selene's 22–29-tool catalogs. A small fixed context profile may outperform dynamic discovery for a predictable workflow.[^8][^9]

The research does not support adding complexity by default. Agentless provides a useful counterexample: a deliberately constrained localization/repair/validation workflow can be competitive in its evaluated setting. Selene should compare composed workflows against its current tools and the host's native tools before expanding the architecture.[^17]

## Foundation: execution, privacy and freshness

### Execution ownership and cancellation

Introduce a single operation coordinator responsible for admission, queueing, cancellation, result ownership and completion. Each operation should carry its project scope, snapshot, deadline, cancellation token and side-effect classification. The coordinator should own these invariants rather than spreading flags across tool wrappers and language adapters.

A timeout must distinguish “the caller stopped waiting” from “the operation stopped.” For edits, keep write ownership until the operation actually stops or the affected worker is terminated and its state reconciled. Reject or quarantine conflicting successor edits during that interval. Retrying a mutation after a timeout also needs an idempotency key or an explicit uncertain-outcome result; automatic replay must not duplicate a change whose first execution may have succeeded.

Cancellation should propagate into cooperative loops, LSP requests and cancellable subprocess groups. Python threads cannot safely be treated as killed by cancelling their future. Where cancellation must stop side effects, use a process boundary or stage proposed changes separately and control the final commit. Validate interruption during reads, edits, cache persistence, diagnostics and project activation, including worker failure.

The current MCP wrapper is synchronous. In the installed SDK, synchronous functions run inline in the protocol event loop, so waiting on the executor also blocks protocol responsiveness. The current SDK v2 migration guide explicitly changes sync handlers to worker threads. That can improve responsiveness, but exposes additional concurrency and therefore makes operation ownership more important.[^14] [Current wrapper](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/mcp.py:66)

### Privacy as an architectural requirement

Keep the approved client as the sole owner of external model calls. Context assembly, graph traversal, lexical search, diagnostics formatting and change planning can all run locally without another AI provider. Hosted vector stores, remote embedding APIs, automatic external rerankers and model-routing fallbacks would introduce recipients and agreements beyond this requirement.

Before expanding indexing or memory, implement the controls identified by the [data-flow audit](/Users/alexp/workspace/side/local-ai-marketplace/selene/DATA_FLOW_AUDIT.md): process-tree network isolation, filesystem/credential restrictions, metadata-only routine logs, private file modes, bounded retention and company-separated storage. A network-disabled Selene process can still communicate with the approved host through stdio. Provision dependencies separately from private project access.

Every new resource handle, cache and graph row must inherit the project/company scope. Handles should not grant access merely because they are difficult to guess. Canonical path checks, mounted filesystem scope and subprocess restrictions must agree. A local graph containing symbol names, paths and relationships is still company data, even if full source text is omitted.

### Freshness and snapshots

Replace repeated full scans with an incremental change journal, fed by filesystem events and explicit notifications from Selene edits. Retain a reconciliation scan for startup, watcher overflow, branch switches and filesystems with unreliable notifications. Merely changing `mtime > previous` to `mtime != previous` fixes decreasing timestamps but still misses preserved timestamps.

Use file identity, nanosecond timestamps and size as inexpensive hints, with content fingerprints where correctness requires them. Introduce an index generation and source-version identity into results, so consumers can distinguish a current answer from one based on an older snapshot. Before mutation, compare authoritative file contents or hashes, regardless of watcher state.

Bound watcher debounce and report when the index is still catching up. Do not return “no references” if the server has not finished indexing; return a partial result with an explicit reason. Coverage and completeness should be first-class fields, particularly for dynamic languages and generated code. [Current notifier](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/ls_manager.py:285)

## Capability 1: context bundles

Add a high-level operation such as `find_context(query, anchors, budget, scope)` that assembles a compact, source-grounded answer for the host model. For a request to change checkout authorization, it could return the relevant handler, called policy function, related types, focused tests, configuration flags and the documentation that describes the intended behavior. Each item should explain why it was selected and identify its file version.

Start with a deterministic retrieval pipeline: explicit paths and symbols first; lexical matches next; then bounded traversal of definitions, references, imports and tests. Use ranking and deduplication to fit a budget, retaining evidence from distinct roles rather than filling the result with near-duplicate callers. Allow the client to request bodies only for selected items.

SQLite FTS5 is a reasonable first candidate for local lexical ranking because it provides full-text queries, BM25 ranking and snippets.[^7] This is a design recommendation, not a performance result for Selene. A code index needs deliberate tokenization of identifiers, paths, camelCase and snake_case; natural-language defaults alone may perform poorly on code.

Keep embedding-based retrieval optional and evaluate it after lexical-plus-symbol baselines. If useful, run the approved embedding model locally with pre-provisioned weights and telemetry disabled. Include the embedding model/version in the index fingerprint and isolate its stored representations like source. Do not silently call a remote embedding service when the local model is missing.

A proposed response should contain items, source versions, evidence relationships, coverage limitations, budget usage and a continuation handle. A representative item might say “test directly calls changed function” or “name-only match; semantic relationship not established.” A result with weak coverage should invite a targeted next step, rather than imply completeness.

The current symbol cache can retain entire file buffers. A new index should separate compact symbol metadata from source content, retrieve bodies from an authoritative snapshot and define how old generations expire. Otherwise a context feature could increase both disk exposure and stale-answer risk. [Existing source-cache behavior](/Users/alexp/workspace/side/local-ai-marketplace/selene/security/cache-data-verification.json)

Acceptance should measure relevant-symbol recall within a fixed output budget, duplicate content, time to the first useful result and task completion. Compare against grep, current symbol tools and a simple repository map. A higher retrieval score alone is insufficient if it causes more editing mistakes or greater end-to-end cost.

## Capability 2: change-impact analysis

Add `analyze_change(diff_or_plan, scope)` to translate a proposed change into an evidence-based impact report. Begin by mapping changed ranges to symbols, then identify direct references, implemented interfaces, callers and tests. Return separate categories for confirmed relationships, heuristic candidates and unresolved dynamic behavior.

For example, changing a public function's parameter should reveal known call sites, interface implementations and tests exercising the function. Changing a JSON field or generated API binding requires another kind of evidence: schema definitions, generation configuration and mappings between generated artifacts. Those relationships should come from dedicated adapters rather than being inferred as certain from matching text.

An initial product can combine current definitions/references/implementations with lexical test discovery. Later, add call hierarchy where the language server supports it, local SCIP imports for large stable repositories, and runtime coverage maps from an explicitly authorized test run. SCIP already models precise code-navigation information; it is a candidate interchange format, not a requirement to upload indexes to a hosted service.[^5]

Test recommendations must disclose their basis. A direct coverage relationship is stronger than a filename heuristic, but neither proves that all affected behavior is covered. Select a fast focused suite for feedback and retain an independently defined broader regression gate before release. Track missed regressions to evaluate the selector.

Cross-repository analysis is a later extension. Require explicit project handles and authorization for each repository, then bind results to their versions. Existing project-query tools are useful transport building blocks; they do not constitute a complete dependency graph or multi-tenant authorization system. Avoid following every visible repository under a user's home directory.

The strongest acceptance cases involve nontrivial changes: interface edits, overloaded names, generated clients, reflection, import aliases, test fixtures and dependency injection. Measure known affected-site recall, uncertainty reporting and the number of regressions missed by selected tests. Do not label the feature a complete “blast radius” calculation when the language/runtime cannot support that guarantee.

## Capability 3: recoverable change plans

Generalize the existing dry-run and occurrence-ID approach into `prepare_change` and `apply_change` operations. A change plan should contain source preconditions, the intended edits, affected paths, predicted diagnostics and a bounded execution policy. The host can review or execute it under its existing authorization; the server should not introduce a second blanket confirmation ritual for work already approved.

Before applying, verify every affected file against the plan's expected version. Stage updates, validate syntax and planned resource operations, then apply with explicit failure handling. A mismatch should return a structured conflict describing what changed and how to regenerate the plan. Preserve unrelated uncommitted user edits.

The current multi-file replacement validates individual occurrences and then applies files in sequence. That is useful protection, but it does not establish transactionality for the whole change. The underlying editor also has direct file-write paths. Introduce journaled recovery and deterministic partial-failure reporting rather than claiming a global atomic filesystem operation. External editors may observe intermediate states unless the design uses an isolated checkout or an equivalent boundary. [Replacement application](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/tools/file_tools.py:420) [File writer](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/code_editor.py:89)

LSP already distinguishes abort, transactional, text-only transactional and undo failure handling. Those are negotiated capabilities, not universal guarantees supplied by every server/client.[^11] Selene should report what its selected backend can actually guarantee and emulate stronger recovery where appropriate.

This abstraction could power API migrations, repeated signature changes, dependency-driven renames and coordinated import updates. Start with operations that already have semantic support; do not synthesize unsafe “move symbol” behavior for languages where imports, visibility and initialization semantics are unresolved.

Acceptance must include concurrent edits, permission failures on the second file, interruption between writes, stale plans, repeated request IDs, Unicode offsets, CRLF files and recovery after process death. A successful response must identify exactly which files changed and which checks completed. Tests should assert observable preservation and recovery behavior, not the internal journal implementation.

## Additional capabilities and performance work

| Opportunity | Concrete value | Boundary or tradeoff |
| --- | --- | --- |
| Failure-to-code context | Convert a stack trace/test failure into related symbols, focused source and likely test entrypoints | Preserve the original error; distinguish evidence from a diagnosis proposed by the client |
| Capability-aware fallback | Return syntax/lexical navigation while a semantic server is unavailable or indexing | Label approximate results; disable unsupported refactorings |
| Local repository map | Supply a compact architectural overview for unfamiliar codebases | Rank by task relevance and budget; do not inject the whole map every turn |
| Structured retrieval batches | Resolve several independent symbols/references in one bounded operation | Fixed allowed operations, bounded fan-out, common snapshot, no arbitrary code execution |
| Memory provenance | Attach project scope, supporting source hashes, owner and validation status to durable decisions | Expire or flag stale claims; avoid automatic cross-project reuse |
| Local change review | Present a navigable plan with source evidence, diagnostics and affected tests | Optional host-supported UI; no remote assets or unauthenticated listener required |
| Language-server lifecycle control | Start required servers on demand and retain a bounded warm pool | Avoid repeated cold starts; evict by measured memory/cost, not a universal timeout |
| Installation/health reporting | Explain missing binaries, capabilities, effective privacy controls and usable commands | Report installed state without automatically downloading or uploading diagnostics |

Tree-sitter can provide syntax structure before a language server is ready and can tolerate incomplete code. It does not supply compiler-level name resolution or prove cross-file references. Treat it as a useful fallback layer, not a replacement for semantic services.[^6]

Cache persistence also deserves profiling. The current tool wrapper calls `save_all_caches` after each tool; cache implementations skip unmodified stores, but a modified store may serialize a growing collection. Measure bytes written and foreground time before choosing bounded deferred flushing, per-file storage or SQLite. Any deferred policy must define crash recovery and comply with retention limits. [Cache calls](/Users/alexp/workspace/side/local-ai-marketplace/selene/src/selene/tools/tools_base.py:412)

Pattern search already uses all available joblib threads. Benchmark a small-task synchronous path and a bounded pool against that baseline, especially when multiple language servers are busy. An optional ripgrep backend could accelerate compatible searches, but must preserve ignore rules, encoding, multiline/regex semantics, ordering and error reporting; unsupported expressions need an explicit fallback. A wholesale rewrite in Rust should wait for profiles identifying a hot path that Python-level scheduling and indexing cannot address.

Typed errors and pagination should accompany these changes. Return stable error codes, retryability, affected scope, completeness, index generation and a bounded continuation handle. Preserve readable text for clients that need it. Some existing tools already shorten results gracefully; generalize that contract instead of presenting pagination as a cure for every long answer.

## MCP and client strategy

The installed MCP SDK is pinned to 1.28.1 and the measured sessions negotiated `2025-11-25`. The current published MCP specification is `2026-07-28`, with a stateless request model and optional extensions.[^12] This is a material compatibility gap to assess, not a reason to replace the working protocol path without client tests.

The July release changes discovery/session assumptions, adds catalog cache hints, and moves long-running Tasks into an extension. It also deprecates legacy HTTP+SSE and selected older capabilities, including Sampling, with a migration window.[^13] Avoid building new Selene model orchestration around a deprecated sampling mechanism; the client can continue to own reasoning and provider selection.

Evaluate SDK v2 in an isolated compatibility branch after operation ownership is defined. Selene subclasses SDK tool classes, patches logging and assigns a private server version field; these integrations need contract tests during migration. The official guide documents changes to context, transports, result handling and synchronous execution, so a version bump alone would be inadequate.[^14]

Long indexing or validation can use Tasks only when the host advertises support. The extension returns durable handles and lets clients poll; a basic client still needs a bounded compatible path or a clear unsupported-capability result.[^15] Test cancellation and restart recovery at the application layer, since a protocol task handle does not itself stop a worker.

Prefer stable, useful tool profiles first. GitHub's MCP server similarly allows selecting tool groups or individual tools to reduce catalog exposure.[^10] Dynamic discovery should be a negotiated enhancement, with stable ordering/descriptions to help host caching. Verify that changing available tools is visible to each supported client; do not assume every host refreshes tools identically.

Client packaging can eventually offer a slim manifest and workflow skill that points at the same local server. Keep the skill concise: explain when semantic tools help, the mutation contract and essential project rules. Avoid duplicating the full tool manual, hardcoding model names, or introducing a second agent framework into the normal path.

## Memory and instructions

Memory should retain durable facts with evidence, not accumulate an unbounded transcript. Each proposed memory record needs a project/company scope, source references, relevant version information and a status such as validated, stale or human decision. Automatic source summaries should be opt-in and generated through the approved client, with local validation of references.

A 2026 study of repository context files found that generated files often harmed success while human-written files gave modest gains in its setting; both could increase exploration and cost. The evaluation was heavily Python-focused and did not establish that security instructions are unnecessary.[^16] The practical implication is to preserve essential policies and hard-to-discover project constraints while testing the incremental value of extra instructions.

For Selene, measure minimal instructions, current instructions and task-specific guidance as separate conditions. Keep security rules invariant across comparisons. Expanding memories should require evidence that they improve tasks beyond information already available from source, configuration and tests. Revalidate or mark stale records after relevant files change.

## Evaluation strategy

The inherited evaluation documents are useful case studies, but they are not a verified improvement baseline for this fork. They rely on agent-selected tasks and agent self-evaluation; the methodology explicitly excludes misuse and asks a model not to question that assumption. The result overview also identifies the evaluated backend as JetBrains and marks results as historical. These choices cannot establish broad reliability for ordinary LSP users. [Methodology](/Users/alexp/workspace/side/local-ai-marketplace/selene/docs/04-evaluation/010_methodology.md) [Historical results](/Users/alexp/workspace/side/local-ai-marketplace/selene/docs/04-evaluation/030_results/000_evaluation-results.md)

Use a paired evaluation: the same repository revision, task, model version, client, reasoning budget and network policy with native tools alone, current Selene, and the proposed feature. Vary execution order, repeat runs where nondeterminism matters, and record failures and timeouts rather than removing them. Freeze the host and dependency versions and separate cold-start from warm-cache results.

Begin with a maintained task set covering navigation, bug repair, multi-file refactoring, interface changes, tests and recovery. Include unfamiliar repositories, generated files, overloaded identifiers, stale indexes, missing toolchains and malformed tool calls. Report Python/TypeScript results separately from Go/Rust and Java/C#; backend coverage should be explicit.

| Measurement | Purpose |
| --- | --- |
| Task success against independent checks | Establish whether the feature helps complete real work |
| Regression and unintended-edit rate | Detect damage concealed by a plausible final answer |
| Relevant-symbol recall at a fixed context budget | Compare context-selection quality |
| End-to-end elapsed time and provider-reported tokens | Measure actual workflow efficiency |
| Local tool p50/p95, startup time, RSS and disk writes | Identify implementation bottlenecks |
| Retry, timeout, cancellation and stale-result rates | Measure operational reliability |
| Unknown/partial coverage rate | Expose unsupported cases without silently claiming completeness |
| Outbound attempts and disallowed-file access | Keep privacy a release gate, not a score traded against speed |

SWE-Bench Pro offers more involved multi-file tasks than simplistic function-completion tests, but its original model scores are historical.[^18] Recent work on SWE-Bench Pro Verified identifies leakage and task-quality problems, while DeepSWE proposes original tasks with explicit functional verifiers.[^19][^20] These are useful inputs to evaluation design; the September 2026 verification paper is a new preprint, and none supplies a measured Selene improvement.

Use only accessible, appropriately licensed benchmark subsets, with independent verification and a separate representative project suite. Protect held-out tests and reference patches from the agent's working environment. Prefer confidence intervals or per-task paired outcomes over a single headline average. Do not claim higher coding success from faster no-op dispatch or fewer schema bytes.

## Prioritized implementation roadmap

Effort ranges below are engineering judgments for an experienced contributor familiar with the codebase. They indicate implementation and focused validation effort, exclude waiting on company/client decisions, and should not be summed into a promised delivery date. Broad language/platform support can exceed these ranges.

| Priority | Work package | Rough effort | Dependency and acceptance gate |
| --- | --- | --- | --- |
| P0 | Strict local data boundary and payload-log minimization | 1–3 weeks for one deployment profile | Synthetic source/credential canaries cannot reach unauthorized destinations or paths; documented storage policy |
| P0 | Operation ownership, cancellation and retry semantics | 1–2 weeks | Timed-out edits cannot overlap conflicting work; interrupted/retried mutations have explicit outcomes |
| P0 | Correct freshness and snapshot identities | 1–2 weeks | Preserved timestamps, branch switches and watcher loss do not produce silently stale mutation inputs |
| P1 | Blocking queue and protocol responsiveness | 2–5 days after ownership design | Reproducible reduction in dispatch overhead; cancellation/control messages remain responsive |
| P1 | Typed results, pagination and capability reporting | 1–2 weeks | Supported clients handle success, partial results and structured failures consistently |
| P1 | Context bundles and local lexical/symbol ranking | 2–4 weeks for Python/TypeScript | Better fixed-budget retrieval and paired task outcomes without privacy regressions |
| P1 | Change-impact and focused test evidence | 2–4 weeks after context foundations | Known affected sites found; uncertain edges labeled; missed regressions measured |
| P1 | Recoverable change plans | 2–4 weeks for initial edit classes | Preconditions, failure injection, user-edit preservation and recovery verified |
| P2 | MCP SDK v2 compatibility and optional Tasks | 1–3 weeks, client-dependent | Current and selected legacy client contracts pass; worker concurrency and restart handling verified |
| P2 | Incremental persistence and bounded server pool | 1–3 weeks after profiling | Lower measured I/O/RSS or cold-start cost without stale answers or retention expansion |
| P2 | Memory provenance and compact workflow guidance | 1–2 weeks | Scope isolation and stale-record behavior verified; instruction benefit measured |
| P3 | SCIP imports, schema/generated-code edges, cross-repo impact, optional UI | 4+ weeks, capability-dependent | Pilot on a justified workload; no claim of uniform language coverage |

For an initial two-week tranche, choose the execution coordinator, event-driven queue, timestamp edge cases, a small real-task benchmark suite, and the first enforceable privacy deployment profile. In parallel at the design level, specify the context/result/change-plan contracts. This tranche is a foundation milestone; it does not complete the whole roadmap.

After the foundation passes, build context bundles before an expansive graph platform. Reuse existing semantic operations and establish that the composition reduces retrieval work. Add impact analysis and recoverable plans as separate changes so their benefits and regressions can be attributed. Expand language/backend coverage only after the same contracts survive realistic failures.

Suggested engineering targets, **not achieved results**, are a sub-10 ms p95 for trivial dispatch on the same machine, no full-project walk for the steady-state no-change fast path when a healthy watcher is available, and a materially smaller relevant-context payload at unchanged task success. Set final thresholds from the representative workload; never relax the privacy or mutation-safety gate to hit a speed target.

## Options to defer or reject

An automatic second AI provider, hosted embeddings, cloud code indexing and remote diagnostics conflict with the intended data boundary unless separately approved. An unbounded “execute arbitrary code over all tools” API would amplify the existing shell/process exposure; a small typed retrieval-composition API has a clearer contract. Larger automatic memories and repository-wide prompt injection should also wait for measured benefit and provenance controls.

Avoid a wholesale language rewrite, a new distributed graph service, and sophisticated multi-agent orchestration as initial work. The current evidence points to local queueing, freshness, tool composition and mutation semantics. Adding a daemon pool before scope isolation could increase cross-project exposure, and adding concurrent writes before cancellation ownership would make an observed bug more consequential.

A local embedding experiment remains reasonable if lexical-plus-symbol retrieval demonstrably misses important cases. A client-specific interactive review surface remains reasonable if it reduces review effort. Both should be optional and justified by a clear task that the simpler baseline fails.

## Evidence boundaries

This assessment reflects the checkout and primary sources available on 13 September 2026. Local measurements use synthetic data and make no AI inference calls. They do not measure commercial model behavior, large-company repositories, every supported language, Docker deployment or OS-wide network confinement. The complete privacy limitations remain in the linked audit.

The proposed context, impact and change-plan capabilities have not been implemented or benchmarked here. Their priority reflects current code, observed bottlenecks and transferable research mechanisms. Published product claims, older model results and new preprints are separated from measured Selene behavior. The roadmap's success criterion is better verified coding outcomes under the approved data boundary.

## Sources

[^1]: John Yang et al. [SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://arxiv.org/abs/2405.15793). 2024; revised 11 November 2024. Primary research on interface design and agent behavior.
[^2]: Di Wu et al. [Repoformer: Selective Retrieval for Repository-Level Code Completion](https://arxiv.org/abs/2403.10059). ICML 2024; revised 4 June 2024. Selective retrieval; completion-task scope.
[^3]: Aider contributors. [Repository map](https://aider.chat/docs/repomap.html). Undated documentation, accessed 13 September 2026. Graph-ranked definitions within a context budget.
[^4]: Sheng Zhang et al. [CodeRAG: Finding Relevant and Necessary Knowledge for Retrieval-Augmented Repository-Level Code Completion](https://aclanthology.org/2025.emnlp-main.1187/). EMNLP, November 2025. Query construction, multiple retrieval paths and reranking.
[^5]: SCIP contributors. [SCIP Code Intelligence Protocol](https://github.com/scip-code/scip). Current repository documentation, accessed 13 September 2026. Index representation and supported indexers.
[^6]: Tree-sitter contributors. [Introduction](https://tree-sitter.github.io/tree-sitter/index.html). Undated documentation, accessed 13 September 2026. Incremental parsing and incomplete-source tolerance.
[^7]: SQLite authors. [FTS5 Extension](https://sqlite.org/fts5.html), sections 5.1–5.2. Undated documentation, accessed 13 September 2026. BM25 ranking and snippets.
[^8]: Anthropic. [Code execution with MCP: Building more efficient agents](https://www.anthropic.com/engineering/code-execution-with-mcp). 4 November 2025. Tool discovery, composition and intermediate-result filtering.
[^9]: Anthropic. [Introducing advanced tool use on the Claude Developer Platform](https://www.anthropic.com/engineering/advanced-tool-use). 24 November 2025. Deferred tool loading; provider-specific evidence.
[^10]: GitHub. [GitHub MCP Server — Tool Configuration](https://github.com/github/github-mcp-server#tool-configuration). Current repository documentation, accessed 13 September 2026. Selected tool groups and individual tools.
[^11]: Microsoft. [LSP 3.17 WorkspaceEdit specification](https://github.com/microsoft/language-server-protocol/blob/gh-pages/_specifications/lsp/3.17/types/workspaceEdit.md). Versioned specification, accessed 13 September 2026. Negotiated failure handling; cited as an established capability, not the latest complete LSP revision.
[^12]: Model Context Protocol maintainers. [Specification 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28). Current published protocol revision, accessed 13 September 2026.
[^13]: Model Context Protocol maintainers. [The 2026-07-28 Specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/). 28 July 2026. Protocol changes, extension framework and deprecations.
[^14]: MCP Python SDK maintainers. [Migration Guide: v1 to v2](https://py.sdk.modelcontextprotocol.io/migration/). Current documentation, accessed 13 September 2026. API changes and synchronous-handler execution semantics.
[^15]: MCP Tasks maintainers. [Tasks extension overview](https://tasks.extensions.modelcontextprotocol.io/). Current documentation, accessed 13 September 2026. Durable handles and negotiated polling behavior.
[^16]: Thibaud Gloaguen et al. [Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?](https://arxiv.org/html/2602.11988v1). 12 February 2026, version 1; sections 4–5. Generated versus developer-written context and Python-focused limitations.
[^17]: Chunqiu Steven Xia et al. [Agentless: Demystifying LLM-based Software Engineering Agents](https://arxiv.org/abs/2407.01489). 2024. Constrained localization, repair and validation workflow.
[^18]: Xiang Deng et al. [SWE-Bench Pro: Can AI Agents Solve Long-Horizon Software Engineering Tasks?](https://arxiv.org/abs/2509.16941). 21 September 2025. More involved repository tasks; original scores are historical.
[^19]: Pujun Zheng et al. [SWE-Bench Pro Verified: A Reliable Benchmark for Software Engineering Agents](https://arxiv.org/abs/2609.08149). 8 September 2026, version 1 preprint. Evaluation leakage and task-quality critique.
[^20]: Wenqi Huang et al. [DeepSWE: Measuring Frontier Coding Agents on Original, Long-Horizon Engineering Tasks](https://arxiv.org/abs/2607.07946). 8 July 2026, version 1 preprint. Original tasks and functional verification.
