# Isolated local stdio deployment

This profile runs Selene and its language-server and shell descendants inside a local Linux container. It is intended for workflows where project data may be returned to the connected AI client but must not be independently transmitted by Selene or its subprocesses. The client remains responsible for the selected AI service, account, processing chain and retention terms.

The verified configuration is Linux ARM64, Docker 29.2.1 and Python 3.11, running in a local VM on an ARM64 Mac. The image includes Pyright 1.1.403. Other language servers, Windows hosts, Docker alternatives and x86-64 have not been verified. The network-filter implementation recognizes native Linux ARM64 and x86-64; that does not establish application compatibility on both platforms.

## Build and connect

Use a Docker daemon controlled by your organization on this machine. Supply its Unix socket explicitly. A Unix socket could itself proxy a remote daemon, so the administrator must establish where that daemon runs. On macOS, the VM must share the selected project at the same canonical path seen by Docker. The launcher does not start a VM, modify Docker contexts or add VM shares.

From the Selene checkout, build the image once:

```sh
python3 -I scripts/build_isolated.py --docker-socket /path/to/local/docker.sock
```

The last stdout line is the immutable local image ID, beginning with `sha256:`. The build provisions public packages and pinned Python dependencies before adding application source. Its context includes tracked `src` files, the isolation modules, the Python dependency manifests and the container entrypoint. It excludes checkout history, memories, logs and host environments. The helper publishes nothing and uses an empty Docker client configuration. Package provisioning requires registry access; it happens before a private project is mounted. A build's image ID fixes its resulting contents, while a later rebuild can resolve different OS package revisions.

Configure the AI client's local stdio MCP command using absolute paths:

```text
command: python3
arguments:
  - -I
  - /absolute/path/to/selene/scripts/run_isolated.py
  - --project
  - /absolute/path/to/the/project
  - --docker-socket
  - /path/to/local/docker.sock
  - --image
  - sha256:<the full local image ID>
  - --context
  - desktop-app
```

The available contexts are `desktop-app`, `ide` and `codex`. Image tags and remote Docker URLs are rejected. Runtime image pulls are disabled. Project paths containing commas or newlines are currently unsupported. The project must be writable by the UID used inside the container; a non-root caller uses its own UID/GID, while a root caller is mapped to UID/GID 65534. Unsupported runtime features or syscall-filter failures abort startup; the launcher has no native fallback.

## Enforced process boundary

The launcher mounts only the selected project at `/workspace`, with recursive bind mounts disabled. The container root filesystem is read-only; `/tmp` is bounded ephemeral storage. It runs as a non-root user with capabilities dropped, no-new-privileges, process and memory limits, and Docker's default seccomp policy. It does not forward registry credentials, SSH agents, cloud keys, proxies or host environment variables into the container.

Docker's `none` network provides only loopback. Before activating the project, Selene loads an additional libseccomp filter inherited by its descendants. It blocks network socket creation, Unix-socket bind/connect, addressed datagrams, descriptor-passing message syscalls and relevant asynchronous syscall paths. Private Unix socket pairs remain usable for event-loop wakeups. The filter augments Docker's default policy instead of replacing it. This closes the Unix-socket path that network namespaces alone do not prevent. [Docker network isolation](https://docs.docker.com/engine/network/drivers/none/), [Docker seccomp](https://docs.docker.com/engine/security/seccomp/), [libseccomp filter loading](https://github.com/seccomp/libseccomp/blob/main/doc/man/man3/seccomp_load.3)

Only stdio descriptors are retained at application startup. The interpreter starts with site initialization disabled and loads the filter using only the standard library, before loading dependency startup hooks or Selene packages. Stdio remains an intentional channel to the connected client. HTTP MCP transports, dashboard access, remote IDE connections, runtime package installation and language servers requiring network sockets are unavailable in this profile.

The host OS, kernel, Docker daemon, image build and administrator remain trusted. This profile does not defend against a compromised host or kernel, intentionally weaken the client's own tools, enforce the client's company contract, or prevent later transfers made outside this container.

## Data retained locally

Ordinary application logging is disabled before project activation. Docker's log driver is explicitly `none`, so daemon defaults such as file logs or remote logging drivers do not capture the MCP stream. The connected client still receives responses and may retain them under its own configuration. [Docker logging drivers](https://docs.docker.com/engine/logging/configure/)

Document-symbol caches operate in memory. The profile sets `persist_symbol_cache: false`, preventing their disk reload and save. Existing caches from prior native sessions are not deleted. Native deployments can also set this option in `selene_config.yml`; its compatibility default is `true`.

Runtime configuration and global session state are stored under the container's ephemeral `/tmp`. Explicit project edits, project configuration and project memories remain in the mounted project. Shell commands can deliberately write files there. The entire selected project is readable inside the container: ignore rules are not a universal secret filter. Mount a project containing only data the connected client is allowed to receive. Symlinks escaping the mount cannot reach host files; they may resolve to files in the public runtime image.

This profile does not retrofit confinement onto a native `selene start-mcp-server` invocation or the older general-purpose Docker/Compose configuration. The earlier data-flow audit continues to apply to those launch paths.

## Verification

See [isolation verification](../../security/isolation-verification.md) for the synthetic control receiver, child inheritance, real MCP/Pyright behavior, filesystem boundary, logging and source-retention observations. These checks are bounded functional evidence, not a capture of every packet, every possible syscall or every language backend.
