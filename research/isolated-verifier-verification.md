# Isolated benchmark submission verification

The [submission verifier](agent_benchmarks/isolated.py) now runs completed candidate code in a disposable local container. It supplies the post-run execution boundary required by the [paired task package](agent_benchmarks/README.md). It starts no agents, selects no provider and establishes no model task-success result.

## Data and execution boundary

The host reads a stopped candidate into bounded regular-file snapshots without importing its code. Symlinks, hardlink aliases, FIFOs and oversized files are rejected. The snapshot preserves exact bytes, including Unicode and CRLF. Limits are 512 files, 2 MiB per file and 8 MiB total. Visible source hashes determine changed and unintended content paths using the same policy as the trusted fixture self-test. File modes, extended attributes and excluded Git/Selene/build/cache contents are outside that accounting.

A private host temporary directory contains the sealed input. Only its `input.json` file is mounted read-only into the container. The input contains the candidate's bytes and that task's checks; the image contains neither the task catalog nor reference repairs. Changes to the original candidate after sealing cannot alter those bytes. The caller must establish that the client has stopped and lost workspace access before sealing; this utility cannot attest to another client's lifecycle or confinement.

The immutable local image runs as UID/GID 65534 with a read-only root, no capabilities, no new privileges, no network, disabled Docker logging, one read-only file mount and ephemeral `/tmp`. It has limits of 128 processes, 1 GiB memory, two CPUs and 256 MiB temporary storage. The existing Linux syscall filter is installed before dependency hooks or candidate imports and inherited by children. Host environment variables and Docker credentials are not forwarded. Only the local Docker Unix socket is accepted, and images are never pulled automatically.

The host bounds attached output to 2 MiB and enforces a configurable 1–120 second deadline, default 90 seconds. Container removal runs on normal completion, errors and timeout; the actual removal result is recorded and required for an automated pass. The inner Python and TypeScript commands also have 30-second limits. Compiler, missing-check and execution failures prevent a pass. Candidate output and diagnostics remain local.

## Executed evidence

The [probe](agent_benchmarks/isolated_probe.py) produced [these results](isolated-verifier-results.json) against the final immutable image:

| Scenario | Observed result |
| --- | --- |
| Three task baselines | All rejected |
| Three reference repairs | All accepted |
| Three plausible regression mutants | All rejected |
| Three unrelated edits with otherwise valid repairs | Functional checks passed; change accounting rejected every edit |
| Fourteen boundary assertions in a candidate module | IPv4/IPv6 socket creation and Unix connect/bind denied; child process inherited denial; parent secret, outside file, daemon socket and reference catalog unavailable; non-root/no-new-privileges verified; verifier/input writes rejected; private socket pair worked |
| Original candidate changed after sealing | Verification used the sealed reference bytes and preserved the changed host file |
| Candidate slept with a live child process | Outer deadline reported timeout and removed the container in 3,058.641 ms |

All fifteen container scenarios behaved as expected, and a final daemon query found no remaining verifier containers. Host snapshot checks also rejected a file symlink, directory symlink, FIFO, hardlink alias and oversized file; Unicode/CRLF bytes survived sealing unchanged. Eight current source hashes match the probe result. Ruff checks, formatting and the research package's type check passed. The shared native fixture self-test was rerun with all twelve expected outcomes; nine result-schema checks and all eighteen prepared workspaces were revalidated.

The output limit and configured resource ceilings are implemented; this report does not claim a separate exhaustive resource-exhaustion stress test. The canaries exercise the listed channels, not every possible kernel escape or side channel.

## Runtime artifact

[Image inspection](isolated-verifier-image-results.json) verified all 617 copied runtime files against the build manifest and confirmed that the base layers match the previously tested isolated Selene image.

- Verifier image: `sha256:8a16567ea070819f82daeedf9eedfa06bb893cd5deba52bf0c1b8db2cdf32fb3`.
- Base image: `sha256:d44c3e3d25949d48ee8af0cc5cb68dff2d5e440b3af967618318b964c69991eb`.
- Linux runtime: Python 3.11.16 and Node 20.19.2. The native fixture environment uses Python 3.11.15; the two timings are not treated as a paired performance measurement.
- Copied dependencies: pytest 8.4.1, pluggy 1.6.0, iniconfig 2.3.0, packaging 26.0, Pygments 2.19.2 and TypeScript 5.9.3.

The build used only previously installed tools and `--network=none --pull=false`; no installation or publication occurred. The dedicated local audit VM exposed only its synthetic fixture directory. Both the image and all results remain local. The regular Selene runtime source and its prior acceptance evidence were not changed.

Reproduce by preparing a new context with `build_context.py`, building `Verifier.Dockerfile` offline against the intended local base, resolving its immutable image ID and invoking `isolated_probe.py` with that image, a local Docker socket, a daemon-shared staging directory and an output path. The context preparation records dependency versions and individual hashes in `tooling.json`.

## Remaining evaluation limits

The independent checks run alongside submitted code after the agent stops. This protects the host and the held-out editing environment; it is not a tamper-resistant grader attestation against a candidate deliberately inspecting or manipulating its own test runtime. Human review remains required, including regression-test quality, documentation and task requirements beyond the automated checks.

The actual approved-client launcher and its native/MCP tool restrictions remain unimplemented and unverified. Client/provider/model selection and authorization for fresh sessions are still pending. Every result therefore reports `agent_scope_verified: false`. Paired model success, provider-token cost, recovery/memory workflows at agent level and representative real-project/backend coverage remain unmeasured. The verifier removes one prerequisite; it does not complete those gates or the separate PR-publication deliverable.
