# Bullpen Socket.IO Security Review (qwen)

Scope: the Socket.IO control-plane interface of Bullpen — the Engine.IO/Socket.IO
handshake, the `connect`/`disconnect` lifecycle, the full set of event handlers
registered in `server/events.py`, and the server-side helpers those handlers
rely on for authentication, origin policy, workspace resolution, input
validation, file/import safety, subprocess execution, and agent prompt
hardening. This is a focused review of the socket.io surface; it complements
the broader deployment reviews in `docs/security-review-2026-06-26.md` and
`docs/security-review-codex-2.md` rather than repeating their Docker/Droplet/
Microsandbox findings.

Threat models:

- Trusted local operator: one person runs Bullpen bound to loopback. Authenticated
  access means trusted operator access. The socket.io interface is a powerful
  local control plane.
- Shared / tunnelled / multi-client: Bullpen is reached over a tunnel, LAN, or
  container, and more than one browser, agent, or local web page can talk to the
  same Socket.IO endpoint. In this mode the handshake, origin policy, and
  workspace authorization become the real security boundary.

## How the Socket.IO interface is secured

- **Handshake authentication.** `connect` is gated: a browser must present a valid
  Flask session, and an MCP/agent client must present a workspace `mcp_token` via
  the Socket.IO `auth` payload. Returning `False` refuses the connection
  (`server/app.py:469-485`).
- **Origin policy.** `cors_allowed_origins` is a callback that allows loopback,
  same-origin / forwarded-origin, or explicit `BULLPEN_ALLOWED_ORIGINS`
  (`server/app.py:131-164`). Engine.IO enforces it on any request that carries an
  `Origin` header (`engineio/server.py:202-213`).
- **Session cookies.** `HttpOnly`, `SameSite=Lax`, and `Secure` under
  `BULLPEN_PRODUCTION=1`, with a capped session lifetime (`server/app.py:216-221`).
- **Login throttling.** 5 failures in 5 minutes blocks for 60s, keyed by IP and by
  IP+user (`server/app.py:271-295`).
- **Workspace scoping for agents.** MCP clients are bound to exactly one workspace
  at handshake and are forced back to that workspace in `_resolve`
  (`server/app.py:485-510`, `server/events.py:586-612`).
- **MCP capability restrictions.** MCP clients are blocked from project admin
  (`project:add/new/import-create/clone/remove`), from all-workspace control
  (`workers:pause_all_automation`, `workers:resume_all_automation`,
  `workers:stop_all_lines`), and from terminals
  (`server/events.py:618-622`, `server/events.py:4149-4153`,
  `server/events.py:4494-4508`).
- **Input validation.** Payload size capped at ~1MB (`server/validation.py:45-50`),
  string/enum/id/slot bounds, terminal input capped at 64KB
  (`server/validation.py:18`, `server/validation.py:186-193`), and terminal
  dimensions bounded (`server/validation.py:177-183`).
- **Path containment.** File operations resolve through `ensure_within`
  (`server/persistence.py:37-43`, `server/file_browser.py:108-113`); project
  registration is constrained by `BULLPEN_PROJECTS_ROOT`
  (`server/workspace_manager.py:41-53`).
- **Import safety.** Archive and bento imports reject path traversal, absolute
  paths, NUL bytes, special/symlink members, nested archives, excessive file
  count, excessive size, and high compression ratio
  (`server/archive_transport.py:128-160`, `server/bento_carrier.py:30-79`).
- **Subprocess discipline.** Git/agent/service commands are run as argument lists
  (no shell interpolation), with timeouts and `start_new_session`
  (`server/events.py:1318`, `server/events.py:5124-5146`); commit hashes are
  validated against `[0-9a-fA-F]{7,40}` before `git show`
  (`server/events.py:1422`).
- **Agent prompt hardening.** Chat history and the current message are wrapped as
  untrusted blocks, and provider argv is hardened for chat / untrusted mode
  (`server/events.py:371-401`, `server/prompt_hardening.py:25-100`).
- **Secret hygiene.** The MCP token is stored in `~/.bullpen/secrets.json` rather
  than `config.json`, and exports strip `server_host`, `server_port`,
  `mcp_token`, and `deploy_label` (`server/mcp_auth.py`,
  `server/archive_transport.py:38-42`).

## Executive Summary

The Socket.IO interface is materially safer than the April/May-era reviews
described: REST endpoints have been retired in favor of events, handshake auth is
enforced, MCP clients are workspace-scoped and capability-restricted, origin
policy is explicit, and the file/import/extract paths have real traversal and
size defenses. For a trusted, single-operator, loopback deployment the baseline is
acceptable.

The residual risk is concentrated in four places: (1) the origin policy treats
*every* loopback origin as trusted, which is a local cross-origin CSRF /
cross-site WebSocket-hijacking vector; (2) the MCP token is a static,
unscoped, long-lived bearer secret that grants full admin of one workspace and is
compared non-constant-time; (3) the browser authorization model is
"any authenticated user is admin of every workspace," with no per-workspace
membership; and (4) `chat:send` can spawn an unbounded number of concurrent agent
subprocesses, unlike the terminal surface which is explicitly rate-capped. None of
these are single missing auth checks; they are product-level authorization,
secrets, and resource-governance gaps that matter most once Bullpen is shared or
tunnelled.

## Findings

### socketio-01 - Medium: Any loopback origin is accepted, enabling local cross-origin Socket.IO CSRF

Evidence:

- Loopback hosts are unconditionally allowed: `_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}`
  and `_socketio_origin_allowed` returns `True` when the origin host is loopback
  (`server/app.py:56`, `server/app.py:141-164`).
- Engine.IO only runs the origin check when an `Origin` header is present and
  otherwise proceeds (`engineio/server.py:206-213`).
- The session cookie is `SameSite=Lax` (`server/app.py:218-220`).

Impact:

A malicious or compromised local web page served from *any* localhost port
(e.g. `http://localhost:9999`) is same-site with `http://localhost:5050`, so the
`Lax` session cookie is sent on the cross-origin Socket.IO handshake/polling
request. The origin check passes because the origin host is loopback. The page can
then open a connection and fire high-impact events — `files:write`, `task:*`,
`worker:start`, `service:start`, `bento:import`, `chat:send`, `project:clone` —
without the operator's consent. This is a genuine local CSRF / cross-site
WebSocket-hijacking vector. It is contained by the loopback-only default bind and
requires a second local web origin to be present or compromised, but it is a real
gap on any machine where Bullpen runs alongside other local web apps or dev
servers.

Recommended work:

1. Do not treat all loopback origins as trusted. Restrict to the exact
   same-origin (scheme+host+port) plus an explicit allowlist of known local
   origins; make the loopback shortcut opt-in via `BULLPEN_ALLOWED_ORIGINS`.
2. Add a per-connection anti-forgery check (e.g. a handshake-origin-bound nonce or
   a per-event CSRF token) so a same-site-different-port page cannot replay
   authenticated events.
3. Document that running Bullpen on the same host as other local web apps raises
   the local-CSRF risk, and that `BULLPEN_ALLOWED_ORIGINS` should be explicit.

### socketio-02 - Medium: MCP token is a static, unscoped, long-lived bearer secret compared non-constant-time

Evidence:

- The token is generated once and persisted: `_generate_unique_token` uses
  `secrets.token_urlsafe(32)` and `ensure_workspace_runtime_config` writes it to
  `~/.bullpen/secrets.json` (`server/mcp_auth.py:115-121`,
  `server/mcp_auth.py:123-141`).
- It is resolved by exact string equality, not constant-time comparison
  (`server/mcp_auth.py:185`).
- It is presented in the Socket.IO `auth` payload at handshake and grants full
  admin of one workspace for the life of the connection
  (`server/app.py:479-488`).
- There is no expiry, no per-event re-auth, and no socket.io-facing rotation
  endpoint (a `rotate_workspace_mcp_token` helper exists but is not exposed as an
  event, `server/mcp_auth.py:192-207`).

Impact:

A single 256-bit token is the entire credential for an agent: it can read/write
workspace files, run `git`, start workers/services, import packages, and drive
`chat:send` within its workspace. Because it is long-lived and unscoped, a leak
(over a non-TLS tunnel, in a log, or from `secrets.json`) is a full-admin
compromise of that workspace. The non-constant-time comparison is not practically
exploitable over the network for a 256-bit token, but it is the wrong primitive
for a bearer secret.

Recommended work:

1. Support token expiry / a `not_after` and expose rotation as a Socket.IO event
   (or a CLI) that invalidates in-flight handshakes.
2. Compare the token with `secrets.compare_digest`.
3. Document that the token is a workspace-admin bearer secret and must not be
   logged, committed, or sent over unencrypted tunnels.
4. Consider scoping the token to a subset of capabilities (e.g. ticket-only vs.
   full workspace) so an agent cannot always reach `chat:send` / `worker:start`.

### socketio-03 - Medium: Any authenticated browser client is admin of every workspace (no per-workspace authorization)

Evidence:

- `_resolve` takes the `workspaceId` from the client payload and falls back to the
  startup workspace; it performs no ownership check
  (`server/events.py:586-612`).
- `_ensure_workspace_membership` will activate and join *any* workspace id the
  client names (`server/events.py:646-664`).
- `project:list` / `projects:updated` expose the full workspace id/name list to
  any authenticated client (`server/events.py:4932-4941`), so ids are not secret.

Impact:

In a shared deployment, user A's session can enumerate all workspaces and then
read, write, move, import, and execute against user B's workspace simply by
naming its id. MCP clients are scoped to one workspace, but browser clients are
not. This is correct for a single-operator tool and is a hard blocker for any
team/customer deployment.

Recommended work:

1. Add per-user workspace membership and enforce it in `_resolve`
   (reject workspaces the session is not a member of) before any handler runs.
2. Restrict `project:list` to workspaces the caller may see.
3. Add roles (view / edit-tickets / edit-files / run-workers / terminal /
   manage-projects / import) so "authenticated" does not mean "full admin."

### socketio-04 - Medium: `chat:send` can spawn unbounded concurrent agent subprocesses (DoS / resource exhaustion)

Evidence:

- `chat:send` starts a new thread per message with no check for an already-running
  run and no per-session or global concurrency cap
  (`server/events.py:5388-5475`).
- `_run_chat` overwrites the `_chat_processes` entry keyed by
  (workspace, session) and launches the agent subprocess
  (`server/events.py:5086-5148`).
- Contrast the terminal surface, which is explicitly limited to 8 per workspace and
  24 per client (`server/terminal.py:67`, `server/terminal.py:120-123`).

Impact:

A client (or a local CSRF page per socketio-01) that sends many `chat:send` events
with distinct `sessionId` values spawns a matching number of concurrent agent CLI
subprocesses, each of which may have filesystem and network access. There is no
rate limit on this path, unlike terminals, so it is the primary resource-exhaustion
vector on the socket.io interface.

Recommended work:

1. Cap concurrent chat runs per workspace and per client (mirror the terminal
   limits), and reject or queue when over the cap.
2. Block a new `chat:send` for a session that already has a running run (or
   require an explicit cancel via `chat:stop`).
3. Add per-event rate limiting across high-impact events (chat, worker/service
   start, import, file-write, project-clone).

### socketio-05 - Medium: Worker trust mode defaults to `trusted`, so worker-executed agents run with elevated permissions

Evidence:

- `normalize_trust_mode` defaults to `trusted` (`server/prompt_hardening.py:14`),
  and `worker:add` / `worker:configure` persist that default
  (`server/events.py:2230`, `server/validation.py:257-259`).
- `harden_agent_argv` only applies hardening when `chat` is true or the trust mode
  is `untrusted`; a `trusted` opencode worker gets `--dangerously-skip-permissions`,
  and a `trusted` claude worker does *not* get `--strict-mcp-config` /
  `--disallowedTools` (`server/prompt_hardening.py:75-100`).

Impact:

The `trust_mode` prompt-hardening model is useful but is the default-elevated
execution boundary for worker-driven agents. A malicious or misconfigured ticket,
an imported worker package, or a hostile repository can drive a worker whose agent
runs with permissions skipped. This is the same gap flagged in the 2026-06-26
review (sec0626-02); it remains the dominant "trusted local" risk.

Recommended work:

1. Default worker `trust_mode` to `untrusted` (as chat already does) and require
   explicit elevation to `trusted`.
2. Add a per-worker execution policy (disabled / manual / restricted / full) that
   is a hard capability gate, separate from prompt trust.
3. In container/cloud/sandbox modes, default shell/service workers, terminals,
   auto-commit, auto-PR, custom env, and provider bypass modes to disabled/manual.

### socketio-06 - Low: `worker:configure` admits arbitrary extra fields into worker slots

Evidence:

- After consuming known fields, `validate_worker_configure` copies every remaining
  string key/value into `sanitized`, blocking only a small `disallowed_runtime`
  set (`task_queue`, `state`, `started_at`, `formula*`, `resolved_value_type`)
  (`server/validation.py:326-338`).
- The handler then applies those fields to the slot and normalizes
  (`server/events.py:3138-3150`).

Impact:

An authenticated client can inject unexpected keys into a worker slot. Most are
harmless, but the open tail widens the surface for smuggling runtime-relevant
fields that a future normalization layer might honor, and it makes the "server owns
runtime state" invariant rely on a blocklist rather than an allowlist.

Recommended work:

1. Flip to an allowlist of configurable fields per worker type and drop the open
   tail, or at minimum log unknown keys.
2. Add tests asserting untrusted payloads cannot set runtime/ownership fields.

### socketio-07 - Low: No TLS by default; `Secure` cookie and MCP token transit cleartext over any non-loopback tunnel

Evidence:

- `SESSION_COOKIE_SECURE` is only set when `BULLPEN_PRODUCTION=1`
  (`server/app.py:214-224`).
- The MCP token is sent in the Socket.IO `auth` payload over whatever transport is
  in use (`server/app.py:479-480`).

Impact:

Bullpen binds to `127.0.0.1` by default, so local use is fine. Any tunnel, LAN, or
reverse-proxy exposure that is not terminated with TLS sends the session cookie,
the MCP token, and all event payloads (including file contents and agent prompts)
in cleartext.

Recommended work:

1. Document that non-loopback access requires TLS termination, and set
   `BULLPEN_PRODUCTION=1` (which also enables `ProxyFix`) in those wrappers.
2. Fail closed on a non-loopback bind without credentials + `Secure` cookies in
   hosted/container modes.

### socketio-08 - Low: Git actions and `project:clone` accept user-supplied URLs without scheme restriction

Evidence:

- `git:action` runs `init/fetch/pull/push/branch/remote`
  (`server/events.py:1551-1583`).
- `project:clone` runs `git clone <url> <path>` with an operator-supplied URL
  (`server/events.py:4879-4886`).

Impact:

Commands are run as argument lists (no shell injection), but the URL is not
restricted to `https`/`ssh`/`git`. Depending on the git build, crafted remote URLs
(`ext::`, `file://`, protocol handlers) can be abused, and `git clone`/`fetch`/
`pull`/`push` of an arbitrary URL is a network egress / SSRF path and can pull in
hostile repository content.

Recommended work:

1. Restrict clone/fetch/push/push URLs to an allowlisted scheme set
   (`https`, `ssh`, `git`, and optionally `file` under explicit local mode).
2. Treat imported/cloned repository content as untrusted (consistent with
   socketio-05) and keep it inside the workspace root.

### socketio-09 - Low: `~/.bullpen` directory permissions are not enforced to owner-only

Evidence:

- The global dir is created with default umask (`os.makedirs`)
  (`server/workspace_manager.py:87-89`).
- The MCP token is written under it (`server/mcp_auth.py:19-20`,
  `server/mcp_auth.py:41-42`). The token file itself is created `0600` via
  `tempfile.mkstemp`, but the containing directory may be world-readable on
  multi-user hosts.

Impact:

On a shared/multi-user host, a sibling local user with read access to
`~/.bullpen` can enumerate `secrets.json` and obtain workspace MCP tokens. Low
impact for the single-user local case.

Recommended work:

1. `chmod 0700` the global dir and `chmod 0600` `secrets.json` explicitly at
   creation and on read.
2. Warn at startup if the dir is group/world-accessible while auth is enabled.

### socketio-10 - Info: Event-level rate limiting is absent outside login and terminals

Evidence:

- Login is throttled (`server/app.py:271-295`) and terminals are capped
  (`server/terminal.py:67`), but the broad set of mutating events
  (`task:*`, `files:write`, `worker:*`, `service:*`, `bento:import`,
  `archive:import`, `project:clone`) has no per-client or per-event rate limit.

Impact:

An authenticated client (or a local CSRF page per socketio-01) can hammer
high-impact endpoints to exhaust CPU, disk, or file handles. This overlaps the
2026-06-26 finding sec0626-05.

Recommended work:

1. Add per-client rate limits on high-impact Socket.IO events.
2. Backpressure `chat:send` (socketio-04) and import/clone behind the same
   limiter.

## Positive Controls (specific to the socket.io interface)

- Handshake rejects unauthenticated upgrades for both browser and MCP clients
  (`server/app.py:469-485`).
- MCP clients are bound to one workspace and forced back to it on every event
  (`server/app.py:485-510`, `server/events.py:586-612`).
- MCP clients are blocked from project admin, all-workspace control, and terminals
  (`server/events.py:618-622`, `server/events.py:4149-4153`,
  `server/events.py:4494-4508`).
- Origin policy is explicit and configurable; `*` is not accepted because
  `_normalize_origin` requires a scheme+netloc (`server/app.py:131-164`).
- Session cookies are `HttpOnly`/`SameSite=Lax`/optional `Secure` with a capped
  lifetime (`server/app.py:216-221`).
- Login has per-IP and per-IP+user throttling (`server/app.py:271-295`).
- File operations are path-contained via `ensure_within` and the tree walker is
  depth/node-bounded and symlink-aware (`server/file_browser.py:116-154`,
  `server/persistence.py:37-43`).
- Archive and bento imports guard against zip-slip, absolute/NUL/symlink members,
  nested archives, size, file count, and compression-ratio bombs
  (`server/archive_transport.py:128-160`, `server/bento_carrier.py:30-79`).
- Payloads are size-capped (1MB) and terminal input is capped (64KB)
  (`server/validation.py:45-50`, `server/validation.py:186-193`).
- Commit hashes are regex-validated before `git show` (`server/events.py:1422`).
- Subprocesses run as arg lists with timeouts and new process groups
  (`server/events.py:1318`, `server/events.py:5124-5146`).
- Chat prompts wrap history/message as untrusted blocks
  (`server/events.py:371-401`, `server/prompt_hardening.py:25-38`).
- The MCP token is kept out of `config.json` and stripped from exports
  (`server/mcp_auth.py`, `server/archive_transport.py:38-42`).

## Prioritized Work List

| Slug | Priority | Description |
|---|---|---|
| socketio-01 | Immediate | Stop trusting all loopback origins; restrict to exact same-origin + explicit allowlist and add a per-connection anti-forgery check. |
| socketio-04 | Immediate | Cap concurrent `chat:send` runs per workspace/client and add event-level rate limits. |
| socketio-02 | Short Term | Add MCP token expiry + socket.io-facing rotation, constant-time compare, and capability scoping. |
| socketio-05 | Short Term | Default worker `trust_mode` to `untrusted` and add a hard per-worker execution policy. |
| socketio-03 | Short Term | Add per-user workspace membership enforced in `_resolve`, and restrict `project:list`. |
| socketio-06 | Short Term | Convert `worker:configure` to an allowlist of fields and test against runtime-field smuggling. |
| socketio-07 | Short Term | Require TLS + `BULLPEN_PRODUCTION=1` for non-loopback binds; fail closed in hosted modes. |
| socketio-08 | Medium Term | Restrict git clone/fetch/push/pull URLs to an allowlisted scheme set. |
| socketio-09 | Medium Term | Enforce `0700` on `~/.bullpen` and `0600` on `secrets.json`; warn on loose perms. |
| socketio-03 | Longer Term | Add RBAC, audit logging, and quotas before any shared/team deployment. |

## Bottom Line

The Bullpen Socket.IO interface is well-defended against the classic remote
vectors — traversal, zip-slip, payload bombs, shell injection, and unauthenticated
handshakes are all handled. The open questions are authorization and governance,
not authentication: the origin policy trusts every local origin, the MCP token is a
broad static bearer secret, browser clients are admins of all workspaces, and
`chat:send` is the one high-impact path without a concurrency cap. For a trusted
single-operator loopback deployment this is an acceptable baseline; for any shared,
tunnelled, or multi-client deployment, the loopback-origin policy, MCP-token
scoping, per-workspace authorization, and chat rate limiting should be fixed first.
