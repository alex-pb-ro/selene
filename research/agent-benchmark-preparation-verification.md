# Agent benchmark preparation verification

The [task package](agent_benchmarks/README.md) prepares an initial paired evaluation of native client tools, prior Selene and the proposed features. It does not run agents. Three authored tasks cover an aliased Python authorization boundary, a required Python currency migration with reflective callers, and a TypeScript interface migration with dependency injection.

## Executable evidence

The trusted-fixture [self-test results](agent-benchmark-package-results.json) contain twelve observations with the expected outcomes:

| Task | Starting version | Reference repair | Regression mutant | Unrelated edit |
| --- | --- | --- | --- | --- |
| Python authorization boundary | Rejected | Accepted | Rejected | Rejected |
| Python required currency migration | Rejected | Accepted | Rejected | Rejected |
| TypeScript gateway request migration | Rejected | Accepted | Rejected | Rejected |

Each unrelated-edit variant passed every functional check and was rejected because it modified a protected file. Thus those rejections exercise change accounting independently of functionality. Reference repairs demonstrate that the authored requirements are satisfiable; they are not model-generated results or exact patches required from future agents. Human review remains required for useful regression coverage, documentation and all other prompt requirements.

The [preparation results](agent-benchmark-preparation-results.json) record eighteen workspaces: three tasks, two repetitions and three conditions. All six matched groups have identical visible file hashes and security instructions across conditions. Only task-visible files, `TASK.md` and `AGENTS.md` were materialized. Every trial remains `not_started` with no result. The local plan is `/tmp/selene-agent-benchmark-trials-v2/trial-plan.json`; it is reproducible with the package's `prepare` command and seed `20260914`.

Nine result-schema checks passed. A complete reviewed result is accepted; success is rejected for timeout, missing verification, pending human review, an unverified privacy gate or unintended changes. Unavailable usage cannot be reported as zero, provider-reported usage requires actual counts, and unsuccessful attempts can retain explicitly unavailable usage. Source and schema hashes in the artifacts match the inspected package.

The self-test used the existing Python 3.11.15 environment and pre-provisioned TypeScript 5.9.3 compiler. Package Ruff checks and formatting checks passed. No runtime source, production tests, prompt templates or project memories changed in this preparation step.

## Boundaries and remaining work

No agents were started, no model calls were made and no task data was uploaded. Native execution was limited to authored fixtures and checks. Its reduced subprocess environment is not an operating-system sandbox. Separating controller files from candidate directories alone does not stop a client from reading them.

Actual trials require an approved client/provider/model, authorization for fresh sessions, verified workspace restrictions for both native and MCP tools, and an isolated submission verifier after the agent stops. The subsequent [isolated verifier](isolated-verifier-verification.md) now has executable evidence for sealed inputs, network/filesystem denial and timeout cleanup. The client launcher and its scope restrictions remain unimplemented and unverified. Those requirements apply before any model trial; the task package does not waive them.

This eighteen-trial plan is a small synthetic pilot. Paired task success, provider-token savings, recovery and memory workflows at agent level, and representative real-project/backend coverage remain unmeasured. The [completion audit](feature-completion-audit.md) retains those open gates and records the published draft PRs.
