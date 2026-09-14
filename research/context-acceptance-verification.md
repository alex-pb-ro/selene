# Comparative context retrieval acceptance

This follow-up evaluates the implemented context service against predefined grep, existing-symbol, repository-map and local lexical workflows. It adds a real TypeScript behavior test and keeps incomplete evaluation criteria visible. It changes no production retrieval code.

## Method

[The probe](probes/context_acceptance.py) creates two synthetic projects: a Python aliased policy import and a TypeScript injected interface. Each contains four independently labelled symbol spans, six relevant files covering code/tests/docs/configuration and 32 similarly named distractors. Every method receives the same query, explicit entry-point anchor and **15,000 JSON-character** first-page allowance. All methods use the same page envelope; the map returns source locations without bodies, while the others can return bodies. Overlapping source ranges are merged in the baselines without using the context service's role-diversity ranking.

Grep uses case-insensitive query-word matches with three surrounding lines. The existing-symbol workflow retrieves the explicit anchor and its direct referencing symbols through the existing retriever. The map lists admitted document symbols and non-code file locations. The lexical workflow supplies the anchor plus up to 50 ranked search results, removing the earlier experiment's twelve-match cutoff. These are deterministic, non-adaptive workflows, not optimized human or agent baselines. Their common metadata envelope differs from raw grep output and a compact custom repository map.

Each method/round starts a fresh project and, where needed, a fresh language-server process. Execution order is shuffled with seed `20260914`. Two rounds each include a first request and a same-process warm repeat: **40 observations** total. Filesystem and dependency caches are not flushed. Cold time below includes project/index initialization, backend startup and the complete first response. Warm time measures the repeated request only. Neither measures streamed arrival of an individual useful item.

In the JSON artifact, `symbol_location_recall` requires the returned versioned source range to contain the **entire labelled span**. It is stricter than finding a name or a method inside the class. `symbol_body_recall` additionally requires those lines in the returned body. This preserves the distinction between a map's navigable locations and code supplied to the client. File recall alone does not establish full symbol coverage.

## Observations

The [final result](context-acceptance-results.json) has no failed workflows and zero overlapping range pairs. Recall was identical across both rounds and warm repeats. The small sample supports per-case observations, not population estimates or reliable p95 latency.

| Python workflow | Full labelled spans | Complete bodies | Relevant files | First-page characters | Median cold ms | Median warm ms |
| --- | --- | --- | --- | --- | --- | --- |
| Grep | 2/4 | 2/4 | 3/6 | 14,705–14,706 | 47.969 | 33.764 |
| Existing symbols | 2/4 | 2/4 | 2/6 | 1,425–1,426 | 2,376.319 | 5.030 |
| Repository map | 3/4 | 0/4 | 5/6 | 14,614–14,616 | 371.659 | 31.023 |
| Anchored lexical | 2/4 | 2/4 | 3/6 | 14,715–14,716 | 42.878 | 30.224 |
| Context bundle | 4/4 | 4/4 | 6/6 | 10,682 | 2,459.803 | 43.772 |

| TypeScript workflow | Full labelled spans | Complete bodies | Relevant files | First-page characters | Median cold ms | Median warm ms |
| --- | --- | --- | --- | --- | --- | --- |
| Grep | 2/4 | 2/4 | 3/6 | 14,819–14,821 | 47.224 | 32.108 |
| Existing symbols | 2/4 | 2/4 | 2/6 | 1,458 | 402.067 | 4.389 |
| Repository map | 3/4 | 0/4 | 5/6 | 14,966–14,967 | 422.797 | 33.540 |
| Anchored lexical | 1/4 | 1/4 | 2/6 | 14,785–14,786 | 42.621 | 29.186 |
| Context bundle | 2/4 | 2/4 | 6/6 | 10,571 | 444.900 | 23.558 |

The Python bundle includes all four full labelled spans, but pays semantic startup cost and is slower than the simpler warm workflows. The TypeScript bundle returns every relevant file while retaining narrower method ranges for parts of the enclosing interface/class. It therefore covers only two full labelled spans. It does not uniformly outperform the map on that metric. An explicit enclosing-type anchor returns its declaration; this follow-up was verified through the real TypeScript test. A `complete` body status describes the selected range, not its containing class or file.

The [initial attempt](context-acceptance-initial-results.json) is retained. Its four lexical workflows failed because the probe requested 64 results while the public search API permits at most 50. The final run corrected that caller error; it did not change production limits or discard failed product cases. Initial successful observations and their older probe hash remain historical.

## Verification and remaining gates

The focused context/impact selection passed 20 tests with Python-marked cases deselected. A subsequent semantic selection passed all six Python/TypeScript cases, including the added explicit-type follow-up, aliased project roots, same-line call sites, Unicode before a reference and stale-handle rejection after an edit with restored timestamps. Formatting and type checks passed. No production source changed, so the previous 1,116-test core result and final isolated MCP runtime hashes still describe the same runtime.

The final comparison records 19 matching runtime/probe hashes. Runtime versions were Python 3.11.15, cached Pyright 1.1.403, TypeScript 5.9.3, TypeScript language server 5.1.3 and MCP SDK 1.28.1. Only synthetic project data was used. No model calls or external evaluation service were involved.

Reproduce with the existing environment, `PYTHONPATH=src`, `UV_OFFLINE=1`, temporary `UV_CACHE_DIR`/`SELENE_HOME`, and a pre-provisioned TypeScript server:

```sh
python research/probes/context_acceptance.py \
  --typescript-server /path/to/typescript-language-server \
  --budget 15000 --rounds 2 --output research/context-acceptance-results.json
```

The research report also calls for paired task completion, unintended-edit rates, provider-reported tokens and representative repositories. **Those gates remain unmeasured.** These retrieval observations cannot establish coding success, end-to-end savings or broad backend coverage. No instruction variants or automatic memories were added, and no instruction-benefit claim is made. The full [completion audit](feature-completion-audit.md) keeps those limits separate from implemented functionality and PR publication.
