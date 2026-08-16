# Pi worker security analysis

## Bottom line

Pi is safe enough for Bullpen's local, single-user worker model when it runs in
a disposable Microsandbox with exactly one host mount: the active project
directory, read/write, at `/project`.

Pi is not a sandbox. Its file and shell tools have all the authority of the Pi
process. The microVM is therefore the security boundary; Pi's trust flags are
only configuration controls.

This design deliberately accepts that Pi can read, change, delete, or
exfiltrate anything inside the mounted project, including `.git`, `.bullpen`,
project `.env` files, and Bullpen-managed worktrees. It is intended to prevent
that authority from extending to the rest of the host filesystem.

The matching implementation specification is [pi-worker.md](pi-worker.md).

## Review basis

- Review date: August 5, 2026
- Upstream: `earendil-works/pi`
- Audited revision: `104364f4c5d48b8136461227e9be0a490c1f72bc`
- Package: `@earendil-works/pi-coding-agent` 0.83.0
- Microsandbox SDK tested locally: 0.5.3

This was a source review of the unattended coding-agent path, not a formal
penetration test. A production dependency audit reported no known advisories at
the audited revision, and a targeted secret scan found no production secret.
Those checks are useful hygiene; they do not change the isolation decision.

## What the Pi source actually permits

Pi's built-in `read`, `write`, and `edit` tools accept absolute paths, `~`,
`..`, and symlinked paths. Its `bash` tool runs arbitrary shell commands and
inherits the Pi process environment. The current working directory is a
starting location, not a filesystem boundary.

Relevant upstream source:

- [path resolution](https://github.com/earendil-works/pi/blob/104364f4c5d48b8136461227e9be0a490c1f72bc/packages/coding-agent/src/core/tools/path-utils.ts#L40-L50)
- [bash execution](https://github.com/earendil-works/pi/blob/104364f4c5d48b8136461227e9be0a490c1f72bc/packages/coding-agent/src/core/tools/bash.ts#L24-L43)
- [inherited shell environment](https://github.com/earendil-works/pi/blob/104364f4c5d48b8136461227e9be0a490c1f72bc/packages/coding-agent/src/utils/shell.ts#L122-L133)
- [Pi's security boundary](https://github.com/earendil-works/pi/blob/104364f4c5d48b8136461227e9be0a490c1f72bc/packages/coding-agent/docs/security.md)

`--no-approve` prevents unapproved project Pi resources from loading. It does
not confine files or commands. Global configuration and ancestor context files
are separate concerns, so managed workers also need a clean agent directory and
`--no-context-files`.

Resource-disable flags are not a complete supply-chain control on their own:
Pi resolves configured packages before filtering disabled extensions and may
install missing packages. `--offline`, an empty managed profile, and a
prebuilt image prevent runtime installation.

In JSON mode, Pi can exit zero even when the final assistant message reports
`error` or `aborted`. Bullpen must inspect that final event rather than trust
the process status alone.

Pi may write complete shell output to temporary files. A small guest-only
tmpfs and the existing Bullpen wall-time/output limits bound this behavior.

## Isolation decision

Each Pi run gets a new microVM with this filesystem view:

```text
host active project  <->  /project       read/write bind
guest image          ->   /opt/...       read-only runtime
guest tmpfs          ->   /tmp           size-limited
guest overlay        ->   /home/pi       disposable
```

There are no other host mounts. In particular, do not mount the host home,
Bullpen source, provider configuration directories, SSH or Docker sockets, or a
shared sandbox home.

The bind source is chosen by Bullpen, canonicalized, and checked before VM
creation. Pi and the model never supply it. `/`, the user's home directory, and
any path broader than the selected Bullpen project are rejected.

The project is mounted directly. There is no copy-in, copy-out, patch import,
or result synchronization. Changes are immediately visible on the host.

### Does `..` escape the project mount?

Inside the VM, `/project/..` is the guest root, not the host project's parent.
Likewise, an absolute host path names a path in the guest. In a local
Microsandbox 0.5.3 check, attempts through `..` and a relative symlink could not
read a marker beside the mounted directory, and a write through
`/project/../...` affected only the guest root.

That behavior is an acceptance test, not an eternal guarantee. It must run
against every supported Microsandbox version. A failure blocks the Pi worker.

## Bullpen MCP parity

Bullpen MCP is mandatory in the first release. Pi has no core MCP client, so
the guest image contains:

- a pinned, reviewed `pi-mcp-adapter`;
- a tiny Bullpen-owned Pi bootstrap that supplies one explicit in-memory MCP
  configuration; and
- the pinned Bullpen MCP stdio server and its runtime dependencies.

The MCP child reads `/project/.bullpen` for the same read operations used by
current providers and connects to the running Bullpen server for mutations.
The workspace MCP token and server address are injected for the run; the host
secret store is not mounted. Ticket and Value writes continue through the live
server so browser clients receive normal events. Direct task-file writes are
not an MCP fallback.

Ambient `.mcp.json`, `.pi/mcp.json`, user MCP configuration, and extension
discovery are disabled. The bootstrap supplies only the Bullpen server. The
initial tool profile is the same `all` profile currently used by the other
provider adapters; changing provider-wide tool policy is a separate project.

The token is a workspace capability available to code inside the VM. It limits
the worker to that Bullpen workspace, but it does not protect the workspace from
Pi. That matches the accepted project-level blast radius and current peer-worker
behavior.

## Required controls

The worker is enabled only when all of these controls are active:

1. A fresh Microsandbox per run, executing as a non-root guest user.
2. One canonical project bind at `/project`, read/write, and no other host bind.
3. A pinned guest image containing Pi, the MCP adapter, the bootstrap, Bullpen's
   MCP stdio code, and required tools. No runtime package installation.
4. A private, guest-only `PI_CODING_AGENT_DIR` with no ambient settings,
   prompts, packages, sessions, or credentials.
5. `--offline`, `--no-session`, `--no-context-files`, all resource-discovery
   disables, and an exact built-in tool list.
6. A minimal environment. No inherited Bullpen, cloud, SSH, package-manager,
   loader, proxy, or host credentials.
7. Provider credentials injected using Microsandbox secret substitution when
   compatible with the selected provider. Host credential directories are
   never mounted.
8. Deny-by-default network policy allowing only DNS to the sandbox gateway,
   the selected model provider's required domains, and the exact Bullpen
   host-gateway address and port.
9. Size-limited guest temporary storage, bounded guest overlay, process/count/
   memory/file limits, Bullpen's 10 MiB stream ceiling, and its outer timeout.
10. Final JSON event validation, deterministic VM termination on success,
    failure, timeout, or yank, and stale-VM cleanup on Bullpen startup.

## Exposure compared with current providers

| Provider path | Filesystem and command authority | Environment | Bullpen MCP |
| --- | --- | --- | --- |
| Claude | Trusted mode can bypass permissions; untrusted mode denies core file/shell tools | adapter starts from the host environment | local stdio server |
| Codex | `workspace-write` locally; configured as `sandbox=none` inside existing container/VM deployments | inherits the host process environment by default | local stdio server |
| OpenCode | broad file/shell ability; ambient/project configuration can merge | adapter starts from the host environment | local stdio server |
| Antigravity | sandbox is off by default unless separately enabled | adapter starts from the host environment | local stdio plugin |
| Proposed Pi | arbitrary file/shell activity inside a per-run microVM; only the selected project is host-mounted | curated guest environment | pinned guest stdio bridge to live Bullpen |

Pi is more dangerous than the other CLIs when run directly on the host because
it has no useful built-in path boundary. Under the proposed design, it has a
smaller host filesystem view and a cleaner environment than Bullpen's current
default provider processes. This does not make Pi harmless: it moves the
accepted loss boundary to the mounted project.

## Residual risk we explicitly accept

- Pi can destroy or disclose the entire selected project and its Git/Bullpen
  metadata.
- A provider credential that cannot use Microsandbox secret substitution may
  be visible to arbitrary code in the guest. Such a provider is disabled until
  an acceptable credential path exists.
- Pi can send project data to the allowed model provider and can misuse Bullpen
  MCP within the token's workspace. Other public and private destinations are
  denied by the required custom network policy.
- Writes to the mounted project consume host disk. Guest tmp/root quotas do not
  quota that mount; timeout and a pre-run free-space check reduce rather than
  eliminate this risk.
- A Microsandbox/virtualization escape remains possible in principle. Pinning,
  upgrade testing, and ordinary host patching are the response.
- If a failed run changed the project, those changes remain. Git or the user is
  the rollback mechanism, as with a direct live working-directory worker.

## Release tests

The provider remains hidden until these tests pass:

- a real provider call works with the pinned Pi invocation and credential path;
- all Bullpen MCP tools are listed, and representative ticket and Value reads
  and writes produce live server events;
- a normal project edit appears immediately on the host;
- host-home, host-parent, absolute-path, `..`, and symlink escape probes fail;
- sandbox inspection shows one host bind and no host credential/socket mounts;
- ambient Pi/project MCP configuration is not loaded;
- JSON success, `error`, `aborted`, malformed, and missing-final-event fixtures
  produce the correct Bullpen result;
- timeout and yank terminate Pi, shell children, MCP children, and the VM; and
- teardown leaves no sandbox while preserving project changes.

## Conclusion

Host-native Pi is not part of this proposal. The isolated Pi worker is
acceptable for Bullpen's local single-user use because its host blast radius is
honestly limited to the exact project the user assigned. MCP parity is part of
that first implementation, not a later enhancement.
