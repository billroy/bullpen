# Electron Conversion Security Analysis (Bullpen)

Date: 2026-04-26
Author: Codex

## 1) Current Project Status

Bullpen is still a Flask + Socket.IO + Vue web application. There is no
Electron scaffold, `package.json`, preload script, `BrowserWindow` setup, or
`node-pty` dependency in the repository as of this review.

The current runtime shape is:

- Backend: Flask + Flask-SocketIO in `threading` async mode.
- Frontend: Vue 3 via CDN, no npm build step.
- Transport: HTTP routes plus Socket.IO events.
- Storage: flat files under each workspace's `.bullpen/` directory.
- Execution: local subprocesses for Claude, Codex, Gemini, Shell workers,
  Service workers, git automation, and GitHub CLI PR creation.
- Multi-project support: a global project registry with workspace-scoped state,
  rooms, and MCP runtime metadata.
- Test surface: `pytest --collect-only -q` currently reports 814 tests.

The README now describes Bullpen as cross-platform and documents optional auth,
MCP integration, Shell / Script workers, Service workers, worktrees, scheduling,
auto-commit/auto-PR, import/export, and hosted/Docker deployment paths. The
Electron plan should therefore be treated as a future desktop packaging track,
not as the current implementation path.

## 2) What Changed Since The April 8 Memo

Several risks called out in the earlier memo have been reduced in the web app:

- Socket.IO origin handling is no longer wildcard/tunnel-suffix based by
  default. It allows loopback, same origin, forwarded same origin, or exact
  `BULLPEN_ALLOWED_ORIGINS` entries.
- Non-loopback binds require authentication credentials before startup.
- Optional username/password auth now supports multiple users, CSRF on login and
  logout, secure cookie flags in production mode, and login throttling.
- Static assets and API routes are gated when auth is enabled, with a small
  public allowlist for the login page.
- MCP tokens are workspace-scoped; MCP sockets are bound to the token's
  workspace instead of being joined to all workspace rooms.
- Workspace exports strip runtime-only `server_host`, `server_port`, and
  `mcp_token`; imports rewrite live runtime metadata after replacement.
- Raw workspace HTML is served as an attachment rather than opened as a live
  same-origin document.
- Zip imports now enforce file-count, total-size, expansion-ratio, traversal,
  absolute-path, and nested-archive checks.
- Prompt hardening exists for worker and chat prompts. Untrusted mode delimits
  user/workspace content and disables auto-commit/auto-PR for AI workers.
- Shell and Service workers use workspace-bounded cwd resolution, explicit env
  construction, secret-like env stripping, and read-only serialization redaction.
- Process tracking is workspace-scoped and subprocess tree termination is tested.

These improvements make the current local web app safer, and they are useful
building blocks for Electron. They do not remove the need for a separate
Electron threat model because Electron would introduce a privileged desktop
runtime and a new IPC/preload boundary.

## 3) Current Security Posture vs Electron Shift

Today, the browser renderer talks to a Python backend over HTTP and Socket.IO.
The backend already has local file, process, git, and agent-execution access.
The main risks are therefore browser-origin control, auth/session boundaries,
workspace isolation, and subprocess policy.

Electron changes the failure mode:

- The network/origin exposure can shrink if the app moves away from HTTP as its
  privileged interface.
- Renderer compromise becomes more severe if the renderer can reach Node,
  preload capabilities, or broad IPC channels.
- Packaging, code signing, auto-update, and Node dependency supply chain become
  part of the security model.

Recommendation remains: do not ship an Electron renderer with direct Node,
filesystem, process, shell, or arbitrary network privileges.

## 4) Electron Architecture Options

### A. Electron shell around the existing local server

This is still the fastest migration.

Pros:

- Reuses nearly all current Flask, Socket.IO, Vue, and test infrastructure.
- Preserves the no-build frontend convention.
- Keeps MCP and current worker execution paths largely unchanged.

Security impact:

- Retains the local HTTP/Socket.IO attack surface.
- Requires the current auth/origin/session model to stay enabled and tested.
- Must bind only to loopback in desktop mode.
- Must prevent arbitrary remote content from navigating into the app window.

This option is acceptable for an internal developer build if it is hardened, but
it is not the cleanest long-term desktop security boundary.

### B. Electron main process + Python worker service behind IPC

This remains the preferred production desktop architecture.

Pros:

- Removes the local network listener from the normal desktop capability path.
- Lets Electron main own privileged operations and expose only typed capability
  channels to the renderer.
- Makes it easier to reason about user intent for file, process, service, and
  terminal-like operations.

Security impact:

- Requires a carefully designed IPC contract.
- A broad or dynamic IPC bridge would be equivalent to backend remote code
  execution.
- The preload bridge becomes a critical security boundary and needs tests.

Recommended target:

- Renderer: untrusted UI only.
- Preload: minimal, versioned `window.bullpen.*` bridge.
- Main process: trusted desktop orchestrator.
- Python process: constrained worker service with the existing validation and
  workspace model carried forward.

## 5) Electron-Specific Controls Required

### BrowserWindow / renderer baseline

- `contextIsolation: true`
- `sandbox: true`
- `nodeIntegration: false`
- `enableRemoteModule: false`
- Disable or tightly control `webview`.
- Block unexpected `will-navigate`, `setWindowOpenHandler`, and external URL
  opens.
- Use a strict CSP for app pages; avoid `unsafe-eval` and new inline script.
- Never load arbitrary workspace HTML into the Bullpen origin. Keep the current
  sandbox/download behavior or isolate previews onto a separate origin/session.

### Preload bridge policy

- Expose a small, versioned API surface.
- Validate every argument at runtime with the same field limits used by
  `server/validation.py`.
- No generic `run(command)`, `read(path)`, `write(path)`, or `invoke(channel,
  payload)` escape hatches.
- Treat workspace IDs, ticket IDs, paths, worker slots, coordinates, and profile
  IDs as hostile inputs until validated.

### IPC policy

- Per-channel schemas and explicit allowlisted channels.
- Request/response correlation with timeouts.
- Workspace scoping on every channel.
- Separate human-user channels from agent/MCP channels.
- Privileged operations require clear user intent and audit events.
- MCP clients should remain bound to exactly one workspace token.

### Packaging / update security

- Code signing and notarization where applicable.
- Signed update feed if auto-update is added.
- Dependency lockfiles and routine dependency scanning.
- SBOM/release artifact provenance before broader distribution.

## 6) Worker, Service, And Terminal-Like Capabilities

The old memo treated an integrated terminal as a proposed future feature.
Bullpen now has several terminal-adjacent capabilities even without a true
interactive PTY:

- Worker Focus Mode streams agent output.
- Live Agent Chat starts provider CLI sessions.
- AI workers launch Claude, Codex, and Gemini subprocesses.
- Shell workers run configured commands against tickets.
- Service workers run long-lived workspace commands and health checks.

These capabilities already represent deliberate local command execution. An
Electron build must keep them out of the renderer.

Required controls:

- Process creation only in Electron main or the Python worker service.
- Renderer receives output streams and sends narrow control intents only.
- Preserve workspace-bounded cwd checks for Shell and Service workers.
- Preserve env allowlisting/secret stripping and redacted read-only views.
- Keep untrusted AI mode disabling auto-commit and auto-PR.
- Audit file writes, subprocess starts/stops, git automation, service starts,
  token rotations, imports, exports, and future PTY sessions.

If a true interactive terminal is added later:

- Use a PTY controlled by main/Python, never renderer.
- Require explicit user-created sessions.
- Limit default cwd to the active workspace.
- Render terminal output through a terminal emulator, never as HTML.
- Guard link opening, OSC 52 clipboard writes, and file/URL handlers.
- Make transcript persistence opt-in because scrollback can contain secrets.

## 7) Prioritized Remaining Work

### P0 before any Electron build is shipped

1. Create an Electron threat model and architecture decision record.
2. Choose shell-around-server vs IPC-first desktop architecture.
3. Add hardened `BrowserWindow` and preload defaults if scaffolding begins.
4. Define typed IPC/preload contracts before exposing privileged operations.
5. Keep local-server desktop mode loopback-only with auth/origin protections if
   option A is used.
6. Add Electron-specific tests for navigation blocking, window-open blocking,
   renderer Node isolation, and preload API validation.

### P1 before enabling desktop command execution broadly

7. Add audit logging for privileged operations.
8. Review all subprocess launch paths for desktop-specific user intent checks.
9. Keep Shell and Service worker commands behind explicit configuration and
   workspace-bounded cwd validation.
10. Preserve untrusted-mode restrictions for auto-commit/auto-PR and make the UI
    clear when a worker is trusted.
11. Add IPC fuzz tests for malformed payloads and cross-workspace requests.

### P2 before public desktop distribution

12. Add signing/notarization/release hardening.
13. Add dependency lockfiles and SBOM/scanning for Electron dependencies.
14. Define update, rollback, and incident-log policy.
15. Document privacy behavior for diagnostics, logs, transcripts, and exports.

## 8) Practical Recommendation

Bullpen is not currently an Electron project. The safest near-term plan is to
continue hardening the Flask/Socket.IO app while preparing an IPC-first Electron
design in parallel.

If speed matters, start with a loopback-only Electron shell around the existing
server as a prototype, but treat it as an interim desktop wrapper. For a real
desktop release, move privileged operations behind a narrow preload + IPC
contract and keep the Python backend as a constrained worker service.

The project is in a better place than the original April 8 memo assumed, but
the core Electron warning still stands: renderer compromise must not become
unrestricted host compromise.
