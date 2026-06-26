# Bullpen Security Review - 2026-06-26

Scope: current Bullpen application code, browser/Socket.IO control plane, worker execution paths, file/import/export paths, MCP/token handling, manager surfaces, and deployment wrappers for local, Docker, DigitalOcean, Sprite, and Microsandbox use.

This review intentionally reads Bullpen through two threat models:

- Trusted local tool: a single operator runs Bullpen like a networked text editor or local automation console. In this mode, authenticated UI access means trusted operator access.
- Container/cloud/sandbox tool: Bullpen runs in Docker, a microVM, a Droplet, or a remote sandbox. In this mode, the browser, mounted workspace, provider credentials, preview app ports, and agent processes become harder boundaries and need explicit policy.

Earlier security reviews considered: `docs/security-review-codex-1.md`, `docs/security-review-codex-2.md`, `docs/security-review-2.md`, `docs/security-review-claude-1.md`, and the dated review packs under `docs/reviews/`. Several earlier high-risk findings have been addressed: localhost is the default CLI bind, non-local binds require credentials, Socket.IO origins are tighter and configurable, login/logout have CSRF protection, MCP clients are workspace-scoped, raw HTML file serving moved off the old REST route, file tree traversal is bounded and symlink-aware, archive imports have traversal/size/file-count/compression controls, and REST APIs have largely been retired in favor of Socket.IO events.

## Executive Summary

Bullpen is now substantially safer than the April and early May reviews described. The current baseline is acceptable for a trusted, single-user local control plane when bound to loopback and when the operator understands that the app can read/write workspace files and start processes.

The dominant risk is now product-level rather than a single missing auth check: once a browser session is authenticated, it can write files, start terminals, configure shell/service workers, run AI agents, clone repositories, import worker packages, and move tickets/workers across workspaces. That is the intended power of the tool, but it is not a tenant-safe authorization model.

The deployment wrappers also create a sharper distinction between "containerized" and "isolated." Docker runs as a non-root user, but it mounts the workspace and a persistent home that can contain provider and Git credentials. The Microsandbox path is stronger because it uses a microVM and constrains project registration under `/workspace`, but it still defaults Codex to no sandbox inside the guest and allows broad outbound network access. The DigitalOcean wrapper has better host hardening, but it deploys a powerful remote admin console and currently lacks response security headers at the app/proxy layer.

## Positive Current Controls

- Socket.IO origin checks now allow loopback, same-origin/forwarded-origin, or explicit `BULLPEN_ALLOWED_ORIGINS`; the earlier wildcard tunnel-origin issue is no longer present (`server/app.py:138-161`).
- Authenticated browser clients receive startup state for the selected workspace and project lists without paths; MCP clients are bound to one workspace (`server/app.py:444-485`).
- Sessions use `HttpOnly`, `SameSite=Lax`, optional `Secure` under `BULLPEN_PRODUCTION=1`, and login throttling (`server/app.py:210-217`, `server/app.py:248-299`).
- The file browser resolves paths under the workspace, skips symlinked directories, and caps tree depth/node count (`server/file_browser.py:40-100`).
- Archive export strips runtime config/secrets, and import rejects traversal, nested archives, excessive file count, excessive size, and high compression ratio (`server/archive_transport.py:38-42`, `server/archive_transport.py:128-160`).
- The Docker image runs Bullpen as a non-root `bullpen` user (`Dockerfile:37-52`).
- The DigitalOcean unit binds Bullpen to `127.0.0.1` behind nginx and enables useful systemd hardening primitives (`deploy/digitalocean/bullpen.service:14-21`).
- Microsandbox deploy constrains project paths with `BULLPEN_PROJECTS_ROOT=/workspace` and starts from `BULLPEN_START_WITHOUT_PROJECT=1` (`deploy-sandbox.py:699-705`).

## Findings

### sec0626-01 - P0: Authenticated Bullpen access is full administrative code-execution access

Evidence:

- Socket.IO file read/write exposes workspace editing to authenticated clients (`server/events.py:1211-1355`).
- Worker start and service start events run configured worker logic (`server/events.py:2821-2829`, `server/events.py:2948-2970`).
- Terminal events create an interactive shell in the workspace and forward input/output over Socket.IO (`server/events.py:3011-3046`).
- Project add/new/clone can expand the set of paths Bullpen operates on unless `BULLPEN_PROJECTS_ROOT` is configured (`server/events.py:3191-3288`).

Impact:

This is correct for trusted local use. It is a blocker for any shared, team, customer, or "semi-trusted browser user" deployment. Password auth currently establishes "this user is an admin," not "this user may view only this workspace" or "this user may edit files but not start processes."

Recommended work:

1. Document "all authenticated users are full admins" in deployment docs and login/setup flows.
2. Add a deployment mode flag, for example `BULLPEN_DEPLOYMENT_MODE=local|sandbox|hosted`, and fail closed on hosted mode until an explicit capability policy is configured.
3. Add per-user roles before any shared deployment: view, edit tickets, edit files, run workers, run terminal, manage projects, import packages, manage credentials.
4. Keep MCP clients scoped to a workspace and extend that model to browser authorization.

### sec0626-02 - P0: Worker execution policy is not separated from prompt trust

Evidence:

- `worker:configure` accepts runtime-affecting fields, including type-specific and unknown worker fields, and then normalizes them later (`server/validation.py:219-327`).
- Shell/service workers and terminals are direct process execution surfaces (`server/events.py:2889-3046`).
- Codex can be configured to bypass approvals/sandbox via `BULLPEN_CODEX_SANDBOX=none`; Docker and Microsandbox default to that value (`Dockerfile:13`, `deploy-sandbox.py:705`).
- Claude runs with `--dangerously-skip-permissions` by design (`server/agents/claude_adapter.py`).

Impact:

The `trust_mode` prompt-hardening model is useful, but it cannot be the primary boundary for malicious tickets, imported worker packages, or hostile repositories. Execution policy needs to be a separate, enforceable capability layer.

Recommended work:

1. Add a per-worker execution policy: `disabled`, `manual`, `restricted`, `full`.
2. In container/cloud/sandbox modes, default shell/service workers and terminals to disabled or manual-confirm.
3. Require explicit policy elevation for auto-commit, auto-PR, shell/service command fields, custom env, terminals, and bypass/sandbox-disabling provider modes.
4. Add tests that untrusted workers cannot silently enable high-impact execution features.

### sec0626-03 - P1: Docker wrapper publishes more than the control plane and copies broad credentials into the container home

Evidence:

- `docker-compose.yml` publishes both Bullpen and app ports by default (`docker-compose.yml:17-19`).
- The optional app profile runs `npm install && npm run dev -- --host 0.0.0.0` (`docker-compose.yml:35-41`).
- `deploy-docker.sh` syncs Claude, Codex, Gemini, OpenCode, GitHub CLI, git config, and optional SSH material into the persistent Docker home or runtime env (`deploy-docker.sh:461-514`).
- The script publishes both Bullpen and app ports to the host (`deploy-docker.sh:545-562`).

Impact:

The Docker path is convenient and non-root, but it should not be described as a strong security boundary when the mounted home contains provider and Git credentials. The published app port can expose project dev servers without Bullpen auth. A compromised workspace process can likely access any credential material mounted into `/home/bullpen` or inherited via env.

Recommended work:

1. Stop publishing `APP_PORT` by default; make it an opt-in profile/flag.
2. Add a deploy prompt summary that says exactly which credentials will be copied or mounted and that agents/workspace commands can read them.
3. Provide a "minimal credentials" mode that forwards only the selected provider for this deployment.
4. Prefer scoped tokens over copying broad host auth directories.
5. Consider Docker read-only rootfs/capability drops where compatible, while preserving the writable workspace and home.

### sec0626-04 - P1: No app-level security headers or CSP

Evidence:

- No `after_request` hook or proxy config adds `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `frame-ancestors`, or HSTS.
- `static/index.html` uses several CDN scripts with SRI, but `lucide@latest`, `@xterm/xterm@5`, and `@xterm/addon-fit@0.10` lack SRI (`static/index.html:15-31`).

Impact:

Bullpen renders untrusted ticket bodies, agent output, file content, and repository metadata in a page that can write files and start processes. Existing markdown rendering and raw HTML handling reduce risk, but a frontend XSS or CDN compromise has high impact.

Recommended work:

1. Add response headers in Flask and mirror/augment them in nginx: CSP, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, and frame restrictions.
2. Pin or vendor all frontend scripts/styles. Remove `@latest` and add SRI for xterm/lucide or serve local copies.
3. Keep CSP initially compatible with the current static app, then tighten away CDN origins once assets are vendored.
4. Add a test that fails on unpinned CDN URLs or missing SRI.

### sec0626-05 - P1: Socket.IO has no visible per-event rate limiting

Evidence:

- The high-impact events include file writes, imports, worker starts, service starts, terminal input, project clone, and chat send (`server/events.py`).
- Login throttling exists, but the Socket.IO event layer does not appear to have token buckets or per-SID rate limits.

Impact:

An authenticated browser session, compromised extension, or accepted malicious origin can cause process churn, large file/binary reads, repeated imports, paid API usage, or terminal spam. Local loopback use lowers exposure but does not remove accidental runaway risk.

Recommended work:

1. Add per-SID and per-workspace token buckets for high-impact event classes.
2. Use tighter limits for `worker:start`, `service:start`, `terminal:create`, `terminal:input`, `chat:send`, `archive:import`, `bento:import`, `files:write`, and `project:clone`.
3. Emit structured rate-limit errors and log them for investigation.

### sec0626-06 - P1: Project root constraints are optional outside Microsandbox

Evidence:

- Project path enforcement depends on `BULLPEN_PROJECTS_ROOT`; when unset, `ensure_within_projects_root()` accepts any real path (`server/workspace_manager.py:17-42`).
- Docker sets `BULLPEN_WORKSPACE=/workspace` but does not set `BULLPEN_PROJECTS_ROOT`; Microsandbox does (`deploy-sandbox.py:699-701`).

Impact:

In local single-user mode this is useful. In Docker/cloud mode, an authenticated browser can register any readable directory visible to the Bullpen process, including mounted homes or config volumes, unless the wrapper constrains projects.

Recommended work:

1. Set `BULLPEN_PROJECTS_ROOT=/workspace` in Docker and hosted deployment wrappers by default.
2. In production/hosted mode, reject `project:add`, `project:new`, and `project:clone` outside configured roots.
3. Add wrapper tests confirming `/`, `/home/bullpen`, `/opt/bullpen`, and symlink escapes are rejected in Docker/Microsandbox profiles.

### sec0626-07 - P2: DigitalOcean deployment lacks proxy-level browser hardening and operational controls

Evidence:

- The nginx config proxies WebSockets correctly but adds no security headers, request/body limits, or auth-rate controls (`deploy/digitalocean/nginx-bullpen.conf:1-20`).
- The systemd unit includes good baseline hardening but still grants write access to `/opt/bullpen`, `/var/lib/bullpen`, and `/home/bullpen/.bullpen` (`deploy/digitalocean/bullpen.service:17-21`).

Impact:

This is reasonable for a single-admin Droplet, but it is a remote attack surface by default once DNS/TLS are enabled. The web UI controls a service account that can edit the workspace and run CLIs.

Recommended work:

1. Add nginx security headers and a conservative `client_max_body_size`.
2. Add fail2ban or app logging patterns for login failures and high-impact event abuse.
3. Split `/opt/bullpen` into read-only app code and writable state/workspace directories.
4. Document that Droplet deployments are single-admin unless RBAC/sandboxed workers are implemented.

### sec0626-08 - P2: Imported worker/package review is improving but should become a policy gate

Evidence:

- Bento imports can strip or require approvals for command/env/service/notification/git capabilities in `server/bento_workers.py`.
- Legacy archive import can still replace `.bullpen` workspace state wholesale after archive validation (`server/archive_transport.py:162-207`).

Impact:

Archive validation prevents traversal and ZIP bombs, but import content can install powerful workers, prompts, columns, and automation settings. A user may treat an import as data when it is actually executable configuration.

Recommended work:

1. Use the Bento capability model as the default import path for worker packages.
2. Add a security preview for legacy workspace/all imports: shell/service workers, terminal-related config, auto actions, schedules, env fields, and prompt changes.
3. Default imported executable workers to paused/manual in container/cloud modes.
4. Add a "dangerous import requires explicit approvals" event contract and tests.

### sec0626-09 - P2: Supply chain is not production-pinned end to end

Evidence:

- Docker installs global npm CLIs without version pins (`Dockerfile:27`).
- The Dockerfile pipes an external installer into bash for Antigravity (`Dockerfile:28`).
- Frontend CDNs are partially pinned/SRI-protected but not complete (`static/index.html:15-31`).

Impact:

Upstream package changes can alter the behavior of an authenticated control plane or agent runtime. This is especially important because the UI and CLIs can write code and run commands.

Recommended work:

1. Pin global CLI versions or build from checked lockfiles.
2. Vendor or checksum external installers where feasible.
3. Generate an SBOM for Docker/Microsandbox images.
4. Add routine dependency scanning for Python, npm/global CLI, and base image layers.

### sec0626-10 - P2: Audit logging and incident review are too thin for hosted use

Evidence:

- High-impact actions are handled as Socket.IO events, but there is no centralized audit log tying actor/session/workspace/action/result together.
- Chat/task transcripts are stored as tickets, but that is not a security audit trail.

Impact:

For local use, terminal/log output may be enough. For cloud or team use, operators need to know who started a terminal, imported a package, wrote a file, registered a project, cloned a repo, changed worker commands, started a service, or triggered auto-PR.

Recommended work:

1. Add structured audit events for high-impact actions.
2. Include session username, source IP, workspace ID, event name, object ID/path/slot, and success/failure.
3. Persist audit logs outside `.bullpen/tasks`.
4. Add an audit viewer/export only after the write path exists.

## Prioritized Work List

| Slug | Priority | Description |
|---|---|---|
| sec0626-01 | Immediate | Update docs and UI copy so authenticated Bullpen users are clearly described as full administrators with file-write and process-execution power. |
| sec0626-06 | Immediate | Add `BULLPEN_PROJECTS_ROOT=/workspace` to Docker and hosted wrappers; keep unconstrained project registration only for explicit trusted-local mode. |
| sec0626-03 | Immediate | Stop publishing Docker `APP_PORT` by default, make dev-server exposure opt-in, and summarize which host credentials will be copied or mounted. |
| sec0626-04 | Immediate | Add Flask and nginx security headers; vendor or fully pin/SRI frontend assets. |
| sec0626-05 | Immediate | Add Socket.IO rate limits for worker/service/terminal/chat/import/file-write/project-clone events. |
| sec0626-02 | Short Term | Introduce worker execution policy separate from prompt `trust_mode`; gate terminals, shell/service workers, auto-commit, auto-PR, provider bypass modes, custom env, and command fields behind it. |
| sec0626-08 | Short Term | Build import risk review as an enforceable gate, not just preview text; default executable imports to paused/manual in container/cloud modes. |
| sec0626-10 | Short Term | Add structured audit logging for high-impact events, including session username, source IP, workspace ID, event name, target object, and result. |
| sec0626-07 | Short Term | Harden the DigitalOcean wrapper with nginx security headers, request/body limits, auth abuse logging, and clearer single-admin deployment documentation. |
| sec0626-01 | Medium Term | Add per-user workspace membership and roles before any shared/team deployment. |
| sec0626-02 | Medium Term | Make hosted/container mode fail closed when auth, project root, secure cookies/proxy headers, and execution policy are not configured. |
| sec0626-03 | Medium Term | Split app code, runtime state, workspace, logs, and credentials into distinct filesystem mounts/permissions for Docker/Droplet. |
| sec0626-09 | Medium Term | Pin and scan runtime CLIs and build dependencies; generate SBOMs for Docker/Microsandbox images. |
| sec0626-03 | Medium Term | Add a safe credential-broker or minimal-credential mode instead of copying broad host credential homes into runtime homes. |
| sec0626-02 | Longer Term | Run workers in per-task or per-worker sandboxes with scoped mounts and network policy. |
| sec0626-04 | Longer Term | Separate Bullpen control-plane origin from preview/dev app origins. |
| sec0626-01 | Longer Term | Add team-ready authorization, audit review, and incident response workflows; treat hosted Bullpen as a privileged remote development environment. |

## Deployment Posture Matrix

| Mode | Current posture | Required before broader use |
|---|---|---|
| Trusted loopback local | Acceptable for one operator | Clear docs; rate limits; security headers |
| LAN/tunnel local | Risky but manageable with auth and explicit origins | Fixed allowed origins, rate limits, project roots, execution policy |
| Docker local | Convenient isolation from host root, not strong credential isolation | Do not publish app port by default; project root; minimal credentials |
| Microsandbox | Best current isolation path | Keep project root; review network/credential policy; avoid default provider bypass modes |
| DigitalOcean | Single-admin remote console | Headers, audit logs, project roots, stricter service filesystem, execution policy |
| Multi-user/team/cloud | Not ready | RBAC, per-workspace authz, sandboxed workers, audit, quotas, control/preview origin split |

## Bottom Line

Bullpen is now defensible as a trusted local automation console and is moving in the right direction for sandboxed local deployment. The next security step is to encode the trust model into the product: local mode can stay powerful and permissive, while Docker, Microsandbox, Droplet, and any hosted mode should get explicit project roots, execution policy, rate limits, security headers, import gates, audit logs, and clearer credential boundaries.
