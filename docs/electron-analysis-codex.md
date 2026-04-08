# Electron Conversion Security Analysis (Bullpen)

Date: 2026-04-08
Author: Codex

## 1) Current Security Posture vs Electron Shift

Bullpen today is a local web app (Flask + Socket.IO + Vue) with file and process access in the Python backend. Moving to Electron changes security boundaries in important ways:

- Today: browser client + local server over HTTP/Socket.IO.
- Electron: privileged desktop runtime where renderer compromise can become local code execution unless process isolation is strict.

Main security shift:
- The browser-origin/network attack surface can be reduced (good), but Electron introduces a high-impact IPC/preload boundary and packaged runtime supply-chain concerns (new risks).

## 2) Security Implications of Electron Architecture Choices

### A. Keep local HTTP server + Electron shell (least refactor)
Pros:
- Fastest migration from current code.
- Reuses most backend logic.

Security impact:
- Retains network/socket attack surface unless bound strictly to loopback and authenticated.
- Still vulnerable to cross-origin/remote control classes of issues if not corrected.

### B. Replace HTTP/Socket with Electron IPC (recommended)
Pros:
- Removes exposed local web server from default runtime.
- Tighter control over capability access via explicit IPC contracts.

Security impact:
- Requires hardened IPC design; bad IPC is equivalent to backend RCE.
- Preload bridge becomes the critical trust boundary.

Recommendation:
- Use Electron main process + Python worker process behind strictly validated IPC.
- No renderer direct filesystem/process/network privileges.

## 3) Electron-Specific Security Controls Required

### BrowserWindow / renderer hardening
Required baseline:
- `contextIsolation: true`
- `sandbox: true`
- `nodeIntegration: false`
- `enableRemoteModule: false`
- Strict navigation policy: block unexpected `will-navigate` and `window.open`.
- CSP for app pages (no unsafe inline/eval).

### Preload bridge policy
- Expose minimal, versioned API surface (`window.bullpen.*`).
- Validate every argument at runtime (schema + bounds).
- No generic “invoke arbitrary command/path” methods.

### IPC policy
- Per-channel schema validation.
- Explicit allowlist channels.
- Request/response correlation and timeout handling.
- Privileged operations require explicit user intent and audit event.

### Packaging / update security
- Code signing for desktop binaries.
- If auto-update is added: signed update feed + TLS pinning strategy + rollback handling.
- Pin JS dependencies and scan (Electron apps are supply-chain sensitive by design).

## 4) Terminal Feature: Security Changes in Electron

Adding an integrated terminal materially increases risk because it is deliberate command execution UX.

### New threat model with terminal
- Renderer compromise can attempt to drive terminal execution.
- Social engineering risk increases (“paste this command”).
- Terminal output can contain escape/control sequences and deceptive links.

### Required controls for terminal subsystem

1. Architecture
- Terminal process creation only in main process (or dedicated privileged worker), never renderer.
- Renderer gets a stream view + controlled input channel.

2. Process model
- Use PTY library (e.g., `node-pty`) with explicit shell path and workspace `cwd` policy.
- Default cwd should be active workspace, not arbitrary filesystem root.
- Explicit environment scrub/allowlist (`PATH`, required vars only; remove sensitive inherited vars by default where feasible).

3. Permissions and intent
- Add a clear session model: user starts/stops terminal explicitly.
- No hidden background terminal commands from automation without a separate confirmation policy.
- Distinguish user-typed commands vs app-triggered commands in audit log.

4. Renderer safety for terminal output
- Use terminal emulator rendering that does not interpret output as HTML.
- Disable/guard risky features:
  - auto-open links without confirmation
  - clipboard write escape sequences (OSC 52) unless user-approved
  - file/URL open handlers without prompts

5. Command execution semantics
- If app exposes “run command” helpers (buttons), pass argv arrays, never shell-concatenated strings.
- If full shell access is intended, document this as a trusted local capability and gate with UX warnings.

6. Data handling
- Terminal scrollback may contain secrets/tokens.
- Make transcript persistence opt-in with retention controls and redaction options.

## 5) Prioritized Issues To Resolve

### P0 (must resolve before shipping Electron build)
1. Process isolation baseline (`contextIsolation`, `sandbox`, `nodeIntegration` off).
2. Remove or strictly lock down local HTTP/Socket exposure (prefer IPC over network).
3. Define and enforce strict preload + IPC schemas for all privileged actions.
4. Fix path traversal surfaces for profile/team/project path inputs in backend logic.
5. Eliminate global broadcast data leakage model; scope events/data by active workspace and authorized view.

### P1 (resolve before enabling terminal feature by default)
6. Implement terminal in main process only with explicit session lifecycle.
7. Add terminal output safety controls (link handling, clipboard/escape handling, no HTML rendering).
8. Add audit logging for privileged actions (file writes, subprocess launches, git automation, terminal sessions).
9. Harden config/event validation to fail closed on unknown/invalid fields.

### P2 (resolve before broader team adoption / multi-host planning)
10. Introduce authentication/authorization model for multi-user future.
11. Replace flat-file coordination assumptions with datastore + stronger concurrency model.
12. Add dependency pinning, SBOM/scanning, code-signing + secure update strategy.
13. Add policy controls for agent/terminal command risk levels (safe/default/unsafe modes).

## 6) Development Approach (Sketch)

### Phase 0: Security foundation and architecture decision
- Decide IPC-first architecture.
- Define trust boundaries document:
  - renderer (untrusted)
  - preload (constrained bridge)
  - main process (trusted orchestrator)
  - Python worker/backend (trusted but constrained)

Deliverables:
- Threat model v1
- IPC contract spec
- Electron security checklist in repo

### Phase 1: Minimal Electron shell (no terminal yet)
- Launch existing UI in Electron with hardened BrowserWindow settings.
- Route backend actions through typed IPC adapters.
- Keep current features working without exposing network listener externally.

Security gates:
- No `nodeIntegration` in renderer
- No wildcard origin/network controls in production mode
- IPC fuzz tests for invalid payloads

### Phase 2: Backend hardening carried into Electron
- Apply strict validation to all mutation channels.
- Fix path handling (`ensure_within` everywhere paths are derived from user inputs).
- Workspace-scoped process tracking and event routing.
- Structured error handling (no raw exception leakage to UI).

Security gates:
- High-severity findings from current review closed.
- Regression tests for path traversal, unauthorized actions, malformed IPC.

### Phase 3: Terminal feature rollout (behind feature flag)
- Implement PTY service in main process.
- Add explicit start/stop terminal sessions per workspace.
- Add output/link/clipboard safeguards and optional transcript policy.
- Add operator warnings for high-risk command execution contexts.

Security gates:
- Terminal abuse tests (escape sequences, untrusted output rendering, command spoof UX).
- Red-team test: compromised renderer cannot execute commands outside approved IPC calls.

### Phase 4: Production readiness
- Code signing and release hardening.
- Dependency pinning and security scanning in CI.
- Incident logging and diagnostic policy (privacy-aware).
- Optional secure auto-update channel.

## 7) Practical Recommendation for This Project

Given Bullpen’s current architecture and risk profile, the safest path is:
- Electron for UX/container,
- IPC-first privileged operations,
- Python backend as a worker service with strict input contracts,
- terminal as an explicitly trusted local capability with strong UX and IPC safeguards.

This preserves development velocity while preventing the common Electron failure mode where renderer compromise becomes unrestricted host compromise.
