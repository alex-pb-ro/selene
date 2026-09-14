# Isolated stdio verification

The isolated profile is implemented on `fix/privacy-boundaries`, based on source-freshness commit `748c9e3`. The original native data-flow audit remains applicable to native launches. This evidence covers a separately provisioned local container profile; it is not a declaration that every deployment or language backend is confined.

## Environment and provenance

Tests ran on 2026-09-14 local time, using a temporary Colima profile named `selene-audit`. The user's existing `default` profile was left stopped and unchanged. The test VM used two CPUs and 2 GB RAM, with only a dedicated synthetic fixture directory shared for MCP filesystem checks. No company project, host home or credential directory was mounted into the test containers.

The guest kernel was Linux `6.8.0-100-generic` ARM64 and Docker was `29.2.1`, reporting default AppArmor, seccomp and cgroup namespace support. The base Python image is pinned by digest in the Dockerfile. The exact tested Selene image ID and source hashes are in [isolated-mcp-results.json](isolated-mcp-results.json). The MCP probe hashes the runtime sources inside the running image and compares them with the checkout. The preserved license is included in that check.

The build helper creates an allowlisted context and uses an empty Docker client configuration. Dependencies are installed before the source-copy layers. It does not push an image. Public registry/package downloads occurred only during provisioning, before a private project was present. No AI model API was called.

## Network control and observations

[The kernel probe](probes/linux_network_boundary.py) creates a separate datagram receiver in a controlled container and exposes its Unix socket through a synthetic shared volume. A control process running with Docker networking disabled successfully sends a marker to that receiver. This demonstrates why network isolation alone is insufficient when filesystem sockets are shared.

After loading Selene's additional seccomp filter, the probe observes `PermissionError` for IPv4, IPv6 and raw socket creation, Unix-socket connection, binding, addressed datagram sends and message sends. The outside receiver receives only the control marker. An executed Python child inherits the restriction. A private socket pair and an asyncio thread wakeup both work. The child has no synthetic parent secret, runs as non-root and reports kernel seccomp mode and no-new-privileges active. See [isolated-network-results.json](isolated-network-results.json).

The implementation keeps Docker's default seccomp policy and adds restrictions through libseccomp. It rejects unsupported architectures and filter failures. The container entrypoint uses Python's isolated/no-site startup, loads the filter before dependency startup hooks, and then activates application packages. It retains only stdio descriptors. The policy is intended for trusted image startup with private mount/process/network namespaces; loading it into an arbitrary already-running process with open external descriptors is not equivalent.

## Real application checks

[The MCP probe](probes/isolated_mcp.py) launches the actual host script and immutable image over stdio. It confirms:

- Selene advertises its name and 29 tools in the tested `desktop-app` context.
- Requested source and a Pyright symbol body reach the connected client.
- A shell command cannot create an IPv4 socket and retains the kernel restrictions and non-root identity.
- A symlink outside the mounted project cannot reveal the separate host canary.
- An authorized file edit becomes visible on the host.
- The synthetic parent secret is not forwarded into the shell.
- Source canaries do not appear in client stderr, Docker daemon logs or project metadata after shutdown.
- Docker reports logging driver `none` and network mode `none`.
- Relevant source files and the license inside the image match the checkout.

The first prototype retained the source canary in two project symbol-cache files. The final profile disables both cache reload and persistence with `persist_symbol_cache: false`; normal in-memory semantic behavior still succeeds. Old native caches are not deleted. A separate refinement disables Docker's log driver so daemon file or remote logging defaults cannot capture MCP stdout.

## Test results and reproduction

Formatting and type checks pass. The affected configuration, manager, Pyright synchronization and isolation selection passed **70 tests**, with one collection skip. After tightening startup ordering and daemon logging, the two real container checks passed again against the updated image. Packaging-only changes are verified by the image/source correspondence check in the final MCP run. Native core regression evidence from the parent freshness change was **1,011 passed and 11 skipped**; a full all-language suite was not run for this profile.

Provision the image with `scripts/build_isolated.py`. The daemon must see the synthetic fixture directory at the same canonical path as the client. Set `PYTHONPATH` to the checkout's `src`, `SELENE_HOME` and `UV_CACHE_DIR` to temporary task directories, and `UV_OFFLINE=1`. To run the optional integration checks via the repository task:

```sh
SELENE_TEST_DOCKER_SOCKET=/path/to/local/docker.sock \
SELENE_TEST_DOCKER_IMAGE_ID=sha256:<local-image-id> \
SELENE_TEST_DOCKER_FIXTURE_ROOT=/absolute/path/to/synthetic-fixtures \
uv run --no-sync poe test -k test_linux_network_boundary -q --tb=short --timeout=70
```

The probe CLIs can also write their result JSON to a chosen local output path. The standard test suite skips these tests unless the explicit local Docker settings are supplied. The fixture receiver, volume and MCP containers are removed by the probes. The temporary VM can be stopped while retaining the built image for later checks.

## Limits

These are real kernel and application observations, not exhaustive packet capture or every-syscall testing. ARM64 with the packaged Pyright backend was exercised; x86-64, other language servers and other container runtimes were not. The host, kernel, Docker daemon, build dependencies and connected client remain trusted. A local Unix socket does not attest that its daemon is local. Client/AI-provider contracts and company policies cannot be verified by this repository.

The entire selected project remains readable to the container, including ignored files. Explicit memories and edits remain in that project, and commands can intentionally write project files. The profile does not constrain tools run by the client outside the container, remove existing native logs/caches, or make native launches safe. See the [deployment guide](../docs/02-usage/073_isolated_stdio.md) for the exact boundary and storage behavior.
