# Pi worker implementation proposal

## Decision

Add Pi as a first-class Bullpen worker provider using one-shot JSON mode inside
a fresh Microsandbox for every run.

The active host project is mounted directly and read/write at `/project`. It is
the only host filesystem mount. There is no worktree copy, result copy, patch
import, or synchronization step.

Bullpen MCP parity is required in the first implementation. A Pi worker gets
the same Bullpen tool catalog as the current providers and performs mutations
through the running Bullpen server.

The security reasoning and accepted residual risk are in
[pi-security.md](pi-security.md).

## User-visible behavior

Pi appears anywhere the existing providers appear:

- worker agent selection and provider color;
- model string configuration;
- availability and setup diagnostics;
- queue, retry, timeout, yank, focus output, usage, and final-result handling;
- optional Bullpen worktrees, auto-commit, auto-PR, and dispositions; and
- the full Bullpen MCP tool set.

The first release supports ticket workers. Agent Chat and persistent Pi RPC
sessions are separate features, not requirements for worker parity.

The model field accepts Pi's normal `provider/model[:thinking]` identifier.
There is no model-catalog service in this change; Bullpen validates length and
passes the configured value to the pinned Pi version.

## Execution contract

Bullpen sends the assembled prompt on stdin and runs the equivalent of:

```text
pi \
  --mode json \
  --no-session \
  --offline \
  --no-approve \
  --no-context-files \
  --no-extensions \
  --no-skills \
  --no-prompt-templates \
  --no-themes \
  --tools read,bash,edit,write \
  --extension /opt/bullpen/pi/bullpen-mcp.js \
  --model <configured-model>
```

The exact binary and extension paths come from the pinned guest image. The
model and prompt are the only per-worker inputs to Pi. The mount source, MCP
server, tool catalog, and runtime flags are owned by Bullpen.

Required guest environment:

```text
HOME=/home/pi
PI_CODING_AGENT_DIR=/run/pi-agent
PI_OFFLINE=1
PI_SKIP_VERSION_CHECK=1
PI_TELEMETRY=0
TMPDIR=/tmp
BULLPEN_MCP_BP_DIR=/project/.bullpen
BULLPEN_MCP_HOST=<guest-reachable Bullpen address>
BULLPEN_MCP_PORT=<active Bullpen port>
BULLPEN_MCP_TOKEN=<workspace token or secret reference>
```

The environment is constructed from an allowlist, not copied from
`os.environ`. Provider-specific variables are added explicitly. Runtime loader,
package-manager, shell override, proxy, cloud, SSH, Docker, and unrelated
Bullpen variables are omitted.

## Sandbox layout

For every worker attempt:

1. Bullpen identifies the configured project root, not the process cwd supplied
   by the model.
2. It canonicalizes the path, verifies that it is the active Bullpen project,
   and rejects broad or unsafe sources such as `/` or the user's home.
3. It creates `bullpen-pi-<run-id>` from a pinned image.
4. It binds the project root read/write at `/project`.
5. It adds a size-limited guest tmpfs and a bounded disposable root overlay.
6. It starts Pi as a non-root guest user.
7. It destroys the VM on every outcome.

The guest cwd is `/project` for ordinary workers. When `use_worktree` is set,
Bullpen creates its normal worktree first and uses the translated path
`/project/.bullpen/worktrees/<task-id>`. This remains a single host mount because
Bullpen worktrees live beneath the project root.

All project changes are live. On failure, partial changes remain in the project
or worktree. Existing Bullpen cleanup and Git behavior remain authoritative;
the adapter does not invent a transaction layer.

The initial deployment target is host-native Bullpen with Microsandbox
installed. Bullpen already running inside Docker or another microVM is not
silently supported because nested VM creation and host-path mounting have
different mechanics. A host-side launcher can be added later if that deployment
is required.

## Bullpen MCP implementation

Pi does not include an MCP client. The guest image therefore pins three pieces:

1. `pi-mcp-adapter`, loaded only through a Bullpen-owned bootstrap;
2. `/opt/bullpen/pi/bullpen-mcp.js`, which calls `createMcpAdapter({config})`
   with a complete in-memory configuration; and
3. a runnable, pinned copy of Bullpen's MCP stdio server and dependencies.

The bootstrap config contains one server:

```json
{
  "settings": {
    "hostConfigDiscovery": "off",
    "directTools": true
  },
  "mcpServers": {
    "bullpen": {
      "command": "/opt/bullpen/venv/bin/python",
      "args": [
        "-m", "server.mcp_tools",
        "--bp-dir", "/project/.bullpen",
        "--host", "${BULLPEN_MCP_HOST}",
        "--port", "${BULLPEN_MCP_PORT}"
      ],
      "env": {
        "BULLPEN_MCP_TOKEN": "${BULLPEN_MCP_TOKEN}"
      },
      "lifecycle": "eager"
    }
  }
}
```

The bootstrap does not ask the adapter to discover configuration and does not
read `.mcp.json`, `.pi/mcp.json`, or user config. `directTools` is enabled for
the Bullpen tools so their names match the worker prompt and existing provider
behavior. The initial tool profile is `all`, matching the current adapters.

Two small changes make the existing MCP server guest-safe:

- `server.mcp_tools` accepts `BULLPEN_MCP_TOKEN` as an explicit token override
  before consulting the host-user secret store; and
- the generated Pi config passes the active server address explicitly rather
  than trusting `.bullpen/config.json`, whose loopback host is wrong from a VM.

The project mount supplies `/project/.bullpen` for existing read operations.
Create/update ticket and Value mutations already go through Socket.IO. The
workspace token binds that connection to the correct live Bullpen workspace.
No Bullpen source or host home is mounted.

MCP setup failure fails the worker run. Shipping Pi without these tools is not
an experimental fallback.

## Runner integration

The current `AgentAdapter` plus `SubprocessRunner` assumes that the agent is a
host subprocess. Do not disguise a microVM as a complicated argv wrapper.
Introduce the smallest explicit execution seam:

```python
class AgentAdapter:
    execution_backend = "subprocess"

class PiAdapter(AgentAdapter):
    execution_backend = "microsandbox"
```

At the existing worker launch point, select `PiSandboxRunner` when the backend
is `microsandbox`; all other providers continue through `SubprocessRunner`.
Both runners return the same captured stdout, stderr, exit status, timeout, and
cancellation outcome expected by the existing result pipeline.

`PiSandboxRunner` has only five responsibilities:

- validate and translate the project/cwd paths;
- create the one-mount microVM with the configured limits and secrets;
- stream the prompt and JSONL output;
- expose a kill method that terminates the whole VM; and
- remove the VM in `finally`.

It reuses Bullpen's existing 10 MiB output ceiling, line/display caps, timeout,
focus events, task retry logic, worktree handling, commit/PR steps, and
disposition processing. A deterministic sandbox name allows yank and startup
reconciliation to remove abandoned runs.

## Output and result handling

`PiAdapter.format_stream_line()` parses each JSON line and renders only useful
assistant text and compact tool activity. Raw thinking and full tool payloads
are not shown by default.

`PiAdapter.parse_output()`:

- requires valid JSONL and a completed final assistant message;
- returns that message's text as the worker result;
- treats final `stopReason` values `error` and `aborted` as failure even when
  Pi exits zero;
- treats malformed/truncated output or a missing final message as failure; and
- extracts provider, model, and token usage when present.

Process status and stderr remain diagnostics. They cannot override a terminal
model error into success.

## Credentials and networking

No host provider directory is mounted. The first release supports provider
authentication that can be passed explicitly to Pi in the guest.

Prefer `Secret.env(..., allow_hosts=[...], require_tls=True)` so the real API
key is substituted only for approved TLS destinations rather than exposed as a
normal guest environment value. Each supported provider must pass a real-call
test because SDK/header behavior determines whether substitution works.

The guest must reach:

- the selected model provider; and
- the active Bullpen server for MCP.

Use a deny-by-default custom `NetworkPolicy`: allow DNS to the sandbox gateway,
the selected provider's documented domains on TLS ports, and the exact Bullpen
host-gateway address and port. Microsandbox 0.5.3 exposes domain, IP/CIDR, port,
and protocol rules for this purpose. If that policy cannot support a provider,
that provider remains disabled; do not silently fall back to unrestricted or
public-wide egress.

The Bullpen listener address presented to the guest is explicit deployment
configuration. A Phase 0 probe must establish the supported host-gateway
address and prove that the workspace token authenticates from the VM. Bullpen
must not widen its listener without its existing authentication protections.

## Code changes

| Area | Change |
| --- | --- |
| `server/agents/pi_adapter.py` | Pi identity, fixed argv, JSONL formatting/parsing, model and usage extraction. |
| `server/agents/pi_sandbox_runner.py` | Path validation, Microsandbox lifecycle, streaming, limits, cancellation, cleanup. |
| `server/agents/__init__.py` | Register `pi`. |
| `server/agents/base.py` | Add the execution-backend marker. |
| `server/workers.py` | Select the sandbox runner while retaining the shared result pipeline. |
| `server/mcp_tools.py` / `server/mcp_auth.py` | Accept an explicit per-run token without reading the host secret store. |
| `server/agents/mcp_config.py` | Generate the in-memory Pi MCP server definition using the `all` profile. |
| validation/init/static provider lists | Add Pi name, color, and model-string UI support. |
| Microsandbox image build | Pin Pi, `pi-mcp-adapter`, bootstrap, Bullpen MCP runtime, and system tools. |
| tests | Adapter fixtures, MCP parity, mount escape, lifecycle, UI, and real first-light coverage. |

No provider-auth UI, model catalog, Agent Chat protocol, remote broker, or
transactional filesystem layer is part of this change.

## Implementation sequence

### 1. Prove the external contracts

Before exposing Pi in the UI:

- run pinned Pi in JSON mode against a real provider using the intended secret
  injection;
- run the pinned MCP adapter with in-memory config;
- reach Bullpen from the guest and call every MCP tool at least once in an
  isolated test workspace;
- confirm direct-tool names match the prompt;
- confirm one project bind and the path-escape regression tests; and
- prove timeout/yank removes Pi, bash/MCP children, and the VM.

If MCP parity fails, implementation stops. Pi is not shipped in a reduced mode.

### 2. Implement the backend and adapter

Add `PiSandboxRunner`, `PiAdapter`, the explicit MCP token override, pinned
bootstrap assets, and unit/integration fixtures. Keep Pi registration behind a
development setting until the Phase 1 acceptance suite passes.

### 3. Add product and Git lifecycle parity

Add validation/UI entries, exercise normal and `use_worktree` workers, and run
the existing success, retry, auto-commit, auto-PR, disposition, timeout, and
yank suites against the Pi backend.

### 4. Release first light

Enable the provider only when the pinned image is available and Microsandbox
passes its startup checks. Report a clear unavailable message otherwise.

## Acceptance criteria

The implementation is complete when:

- Pi is selectable and completes an ordinary Bullpen ticket;
- the active project is the sole host mount and edits appear immediately;
- `~`, absolute paths, `..`, and symlinks cannot expose host files outside it;
- all Bullpen MCP tools are present and representative ticket/Value changes
  generate normal live events;
- a worktree-enabled Pi worker edits the normal Bullpen worktree without a
  second mount or any copy step;
- ambient host credentials, Pi config, MCP config, and Bullpen source are not
  visible in the guest;
- structured success and failure are classified correctly;
- output, runtime, process, memory, and guest-disk limits are enforced;
- timeout and yank remove the microVM without losing already-written project
  changes; and
- existing commit, PR, retry, and disposition behavior passes unchanged.

## Open items with owners and decisions

These are validation tasks, not invitations to redesign the worker:

1. **Guest-to-Bullpen address:** deployment code must identify and test the
   Microsandbox host-gateway address. If no supported route exists, add a small
   authenticated host listener; do not add a filesystem mount.
2. **Pinned MCP version:** security review pins the exact `pi-mcp-adapter`
   version and dependency lock used by the image. If its in-memory configuration
   or discovery controls fail review, replace only that component with a small
   Bullpen-owned Pi MCP client; MCP parity remains mandatory.
3. **Provider credentials:** enable only provider/model combinations that pass
   the real `Secret.env` test. OAuth-directory copying is not added to this
   implementation.

Nothing else in the earlier issue list blocks this design. Enhancements can be
opened when a concrete user need appears.
