# Paired agent benchmark task package

This package prepares matched coding tasks for the evaluation requested in the research report. It starts no agents, selects no provider and uploads no data. Its self-test validates the authored tasks and graders; it is not an agent benchmark result.

## Tasks and independent checks

| Task | Work requested | Independent checks |
| --- | --- | --- |
| `python_authorization_boundary` | Follow an aliased checkout/policy call, fix an inclusive configurable boundary and add regression coverage | Zero and multiple non-default limits, values above/below the limit, negative amounts, suspended accounts and changed configuration between calls |
| `python_required_currency_migration` | Introduce a required keyword-only currency argument; update invoices, refunds, reflective export lookup, tests and documentation | Public call signature, exact large-integer formatting, invalid inputs, all three caller styles and unrelated same-named display behavior |
| `typescript_gateway_request_migration` | Replace a numeric interface argument with a typed currency request; update implementation, injected caller, tests and documentation | Compile-time rejection of missing/unsupported currencies, per-currency boundaries, forwarded request values, injected denial and unrelated overload behavior |

Each task has immutable visible starting files, a prompt, an edit scope, protected unrelated files, controller-owned checks and an authored reference repair. The reference is one valid implementation, not an exact patch the agent must reproduce. Each also has a plausible regression mutant. The unrelated-edit variant preserves functionality while changing a protected file, so its rejection verifies change accounting separately from functional failures.

The task prompts also require useful regression coverage and, where relevant, accurate documentation. Automated checks alone do not prove those qualitative requirements. A human must review all prompt requirements before a trial may be labelled successful. Recovery fault behavior and memory staleness already have separate executable probes; this initial three-task set does not supply a full agent-level evaluation of those workflows or a representative real-project suite.

## Self-test

Use the existing Python environment and pre-provisioned TypeScript compiler:

```sh
.venv/bin/python research/agent_benchmarks/run.py self-test \
  --typescript-compiler /path/to/node_modules/.bin/tsc \
  --output research/agent-benchmark-package-results.json
```

The command executes only the trusted baselines, reference repairs and authored mutants. Expected outcomes are: baseline rejected, reference accepted, regression mutant rejected, and unrelated edit rejected while its functional checks still pass. Missing tests, skipped tests, compilation errors, verifier timeouts and execution errors prevent an automated pass. Results retain the failing check details. The subprocess environment omits inherited credentials and plugin autoloading; this is not an operating-system sandbox or an adversarial grader attestation.

## Prepare matched trials

```sh
.venv/bin/python research/agent_benchmarks/run.py prepare \
  --output-directory /tmp/selene-agent-benchmark-trials \
  --repeats 2 --seed 20260914
```

The output directory must not already exist. This prepares 18 workspaces: three tasks, two repetitions and three conditions. Condition order is shuffled reproducibly within each task/repetition. The visible file hashes and security instructions are identical across the three conditions in each pair. `trial-plan.json` stays outside each agent workspace, and all trials initially have `status: not_started` and no result.

- `native`: the approved client's ordinary local tools, without the MCP server.
- `prior_selene`: the same client/native tools plus the prior server at source commit `5dc6cbd3ce9d59799774f2a22fe97c846d555196`.
- `proposed_selene`: the same client/native tools plus server commit `23f84eac01b99ac8ee87b9d91f6f873c11e4a260`, enabling the ten added index/context/impact/change-plan/memory tools listed in the plan.

These source revisions identify server code, not task starting files. The current main checkout has removed server source and is not a usable prior-server condition. Pre-provision both server environments and language tools before granting access to task data. Record the actual initialized tool catalogs, configuration and source hashes; simply naming a branch is insufficient proof that the intended tools were active.

## Before running agents

Fresh agent sessions require explicit authorization. Choose one approved client/provider and freeze its client version, model version, reasoning budget and network policy across all conditions. No alternate provider, hosted index, external diagnostics or model-generated hidden checker is part of this package. Native-tool availability and essential security instructions must remain constant; context/tools added by the MCP condition are part of the measured difference.

Restrict **all** agent tools to that trial's workspace, including the client's native shell and file tools. The agent must not see this controller directory, reference repairs, graders, other trials or previous results. A directory layout or an instruction saying not to read them does not enforce isolation. The isolated MCP profile alone cannot confine a client's separate native tools. Verify the client-side boundary before recording a valid trial.

Stop the agent before taking the final candidate snapshot. Inject the independent checks only into a separate verifier environment after the agent has lost access. Run agent-authored code under an isolated filesystem/network profile with no credentials; the native `self-test` command is intentionally not a generic submission runner. The actual approved-client launcher and isolated submission-verifier adapter remain to be integrated and verified. No trial should be run with those requirements waived merely to obtain a score.

## Recording and interpreting outcomes

Record every attempt using [trial-result.schema.json](trial-result.schema.json). A success requires a completed attempt, passing independent checks, no unintended paths, passing human review and a verified privacy gate. Missing provider token usage is explicitly `null` with source `unavailable`, not zero or a character-based estimate. Such a result cannot establish a provider-token efficiency comparison even if its coding task succeeds.

Retain failures, timeouts, cancellations and setup errors. A retry is another identified attempt; it must not replace an unsuccessful observation. Measure time from agent start to its final response separately from post-run verification. Preserve candidate diffs and controller logs locally, with hashes connecting results to the starting files, server revision and tool catalog. Do not upload them without the explicit publication authorization already requested for this project.

Report each task and condition separately before considering aggregate numbers. Two repetitions on three authored tasks are a pilot, not a confidence interval for coding success. The package makes future measurement reproducible; it does not close the currently unmeasured task-success, provider-cost, real-repository or broad-language acceptance gates.
