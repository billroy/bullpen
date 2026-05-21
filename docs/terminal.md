# Web Terminal Tab Specification

**Status:** Ready for implementation planning  
**Created:** 2026-05-21  
**Sources:** `docs/features-4.md` item 7, `docs/web-terminal-survey.md`

---

## Summary

Add a first-class **Terminal** tab type to Bullpen. Each terminal is an interactive PTY-backed shell running on the Bullpen server, rooted in the active workspace directory. Operators can open multiple terminals per workspace, switch between them as regular right-pane tabs, close them independently, and use them for project-local commands without leaving the browser.

The recommended implementation is **xterm.js + FitAddon on the frontend** and a small **Python PTY session manager bridged over the existing Flask-SocketIO connection** on the backend.

This is intentionally a local/developer feature, not a remote multi-user terminal product. It should inherit Bullpen's current assumptions: single-host execution, workspace-scoped state, and authenticated browser access.

---

## Goals

- Provide an interactive web terminal inside Bullpen's right-pane tab bar.
- Start each terminal in the current workspace root, not in `.bullpen/` or the Bullpen app directory.
- Allow multiple terminals per workspace.
- Keep terminal tabs workspace-scoped; switching projects shows that project's terminals only.
- Preserve terminal processes while the user switches tabs.
- Support common interactive shell behavior: ANSI output, control keys, resizing, curses-like programs, `Ctrl+C`, `Ctrl+D`, shell prompts, full-screen editors where practical.
- Reuse Bullpen's existing Socket.IO connection and tab architecture.
- Avoid adding a frontend build step or npm dependency.

## Non-Goals

- No persistent terminal replay across server restarts.
- No terminal sharing between separate browser clients in the first iteration.
- No file-backed transcript storage in `.bullpen/`.
- No terminal access for MCP-authenticated agent clients.
- No per-command allowlist or sandboxing in this feature. A terminal is equivalent to shell access as the Bullpen server user.
- No embedded SSH server, ttyd, GoTTY, Wetty, or separate Node service.

---

## User Experience

### Entry Points

Add a terminal creation control to the tab bar:

- A small terminal icon button in the tab bar add area.
- Existing `+` behavior may remain for Live Agent tabs, but terminal creation should be visually distinct, either:
  - `+` opens a compact menu with "Live Agent" and "Terminal", or
  - keep `+` for Live Agent and add a terminal icon button beside it.

Recommended first pass: add a terminal icon button with tooltip "New terminal".

### Tab Behavior

Terminal tabs appear alongside existing right-pane tabs:

```text
 Tickets | Workers | Files | Commits | Stats | Live Agent | Terminal | Terminal 2
```

Each terminal tab:

- Has an icon: `terminal` from lucide.
- Has a workspace-scoped label: `Terminal`, `Terminal 2`, `Terminal 3`, etc.
- Is closeable.
- Belongs to exactly one `workspaceId`.
- Is hidden when a different workspace is active.
- Keeps its PTY running when another tab is selected.

Closing a terminal tab:

- Prompts if the PTY process is still alive:
  - "Close this terminal and stop its shell?"
- Sends a server-side close event.
- Removes the tab after the server acknowledges closure or after a short timeout if the socket is already disconnected.

### Terminal Pane

The terminal content fills the right-pane tab content area.

Expected controls:

- Terminal viewport using xterm.js.
- Small header/toolbar above the terminal or integrated into the tab content top edge:
  - Connection/status pill: `starting`, `running`, `exited`, `error`.
  - Optional current working directory display if reported by the server. This is informational only; the shell remains authoritative.
  - Restart button when exited.
  - Close button may remain only in the tab itself.

The terminal must focus when:

- The terminal tab is opened.
- The user clicks inside the terminal.
- The active terminal tab is selected again.

The terminal should call FitAddon:

- After mount.
- After tab activation.
- After right-pane resize.
- After left pane collapse/expand.
- On `window.resize`.

### Multiple Terminals

The user may open more than one terminal in the same workspace. Each terminal is backed by a separate PTY process and independent shell session.

Initial limit:

- Maximum 8 live terminals per workspace.
- Maximum 24 live terminals per browser session across all workspaces.

If the limit is reached, show a toast and do not create another terminal.

### Workspace Rooting

When a terminal is created, the server resolves the workspace path from `workspaceId` and spawns the shell with:

- `cwd = manager.get_workspace_path(workspaceId)`
- Environment variable `BULLPEN_WORKSPACE` set to that same path.

For Docker deployments, this will normally be `/workspace`.

### Shell Choice

Default shell selection:

1. `$SHELL` if present and executable.
2. `/bin/zsh` on macOS if executable.
3. `/bin/bash` if executable.
4. `/bin/sh`.

The first iteration does not need a UI shell picker.

Future option: workspace config field `terminal_shell`.

---

## Functional Requirements

### Terminal Creation

When the user clicks "New terminal":

1. Frontend creates a local tab placeholder with status `starting`.
2. Frontend emits `terminal:create` with `{ workspaceId, terminalId, cols, rows }`.
3. Backend validates workspace membership and terminal limits.
4. Backend spawns a PTY process rooted in the workspace.
5. Backend emits `terminal:created`.
6. Frontend activates the tab and focuses xterm.

`terminalId` should be generated client-side with `crypto.randomUUID()` and treated as opaque.

### Input and Output

- Frontend sends user keystrokes as raw strings via `terminal:input`.
- Backend writes those bytes to the PTY master FD.
- Backend reads PTY output and emits `terminal:output`.
- Frontend writes output directly to the xterm instance.

Output should be chunked and emitted as soon as practical. Do not line-buffer PTY output.

### Resize

When xterm dimensions change:

- Frontend emits `terminal:resize` with `{ cols, rows }`.
- Backend applies the size to the PTY using `TIOCSWINSZ`.
- Backend may ignore invalid sizes.

### Exit

When the shell exits:

- Backend emits `terminal:exit` with `{ code, signal }` where available.
- Frontend marks the terminal as `exited`.
- The tab remains open and shows the final buffer.
- User may close or restart it.

### Restart

Restarting an exited terminal:

- Reuses the same terminal tab and `terminalId`.
- Clears xterm only after the backend confirms the new PTY started.
- Starts again in the workspace root.

### Disconnect and Reconnect

First iteration behavior:

- Browser socket disconnect does not immediately kill PTYs.
- Backend marks PTYs owned by that browser SID as detached.
- PTYs are retained for a short grace period, recommended 2 minutes.
- If the same browser reconnects and requests `terminal:list`, it may reattach to retained PTYs if a stable owner token is available.

Minimal acceptable implementation:

- On disconnect, terminate all PTYs for that SID.
- Document this limitation in the UI by marking terminals as disconnected.

Preferred implementation:

- Store a per-page `terminalClientId` in `sessionStorage`.
- Include it in terminal events.
- Backend maps `(terminalClientId, workspaceId, terminalId)` to PTY sessions.
- On reconnect, frontend emits `terminal:list` and reattaches tabs for retained sessions.

---

## Socket.IO API

All events are browser-client only. MCP-authenticated clients must be rejected.

### Client to Server

#### `terminal:create`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid",
  "clientId": "session-storage-uuid",
  "cols": 120,
  "rows": 32
}
```

#### `terminal:input`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid",
  "data": "raw input bytes as string"
}
```

#### `terminal:resize`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid",
  "cols": 120,
  "rows": 32
}
```

#### `terminal:close`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid"
}
```

#### `terminal:restart`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid",
  "cols": 120,
  "rows": 32
}
```

#### `terminal:list`

```json
{
  "workspaceId": "workspace-id",
  "clientId": "session-storage-uuid"
}
```

### Server to Client

#### `terminal:created`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid",
  "label": "Terminal 2",
  "status": "running",
  "cwd": "/path/to/workspace",
  "pid": 12345
}
```

`pid` is optional and should only be used for debugging display if exposed at all.

#### `terminal:output`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid",
  "data": "raw PTY output string"
}
```

#### `terminal:exit`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid",
  "code": 0,
  "signal": null,
  "status": "exited"
}
```

#### `terminal:closed`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid"
}
```

#### `terminal:error`

```json
{
  "workspaceId": "workspace-id",
  "terminalId": "uuid",
  "message": "Unable to start shell"
}
```

#### `terminal:list`

```json
{
  "workspaceId": "workspace-id",
  "terminals": [
    {
      "terminalId": "uuid",
      "label": "Terminal",
      "status": "running",
      "cwd": "/path/to/workspace"
    }
  ]
}
```

---

## Frontend Technical Design

### Dependencies

Add xterm assets to `static/index.html` via CDN, matching Bullpen's current no-build approach:

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5/css/xterm.css">
<script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5/lib/xterm.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10/lib/addon-fit.js"></script>
```

Implementation should add SRI hashes before merge if CDN source supports stable integrity metadata.

### New Component

Add `static/components/TerminalTab.js`.

Responsibilities:

- Create `new Terminal({ cursorBlink: true, convertEol: false, scrollback: 5000, fontFamily: ... })`.
- Load FitAddon.
- Attach `term.onData(data => emit('terminal-input', { terminalId, data }))`.
- Observe container resize and emit `terminal-resize`.
- Expose methods:
  - `fit()`
  - `focus()`
  - `write(data)`
  - `clear()`
  - `dispose()`

Props:

- `terminal`
- `active`
- `workspaceId`

Events:

- `terminal-input`
- `terminal-resize`
- `restart-terminal`

### App State

Add reactive terminal tab state in `static/app.js`:

```js
const terminalTabs = reactive([]);
// [{ id, terminalId, workspaceId, label, status, cwd }]
```

Add refs for component instances:

```js
const terminalTabRefs = reactive({});
```

Add helpers:

- `addTerminalTab({ activate = true } = {})`
- `closeTerminalTab(tabId)`
- `restartTerminal(tabId)`
- `terminalTabsForWorkspace(wsId)`
- `terminalTabById(tabId)`
- `ensureTerminalClientId()`

Tab IDs should be distinct from other dynamic tabs:

```js
id: 'terminal-' + terminalId
```

### Tab Integration

Update `allTabs`:

- Include terminal tabs for the active workspace.
- Mark with `isTerminal: true`.
- Use lucide icon `terminal`.
- Make closeable.

Update the tab bar:

- Add a terminal creation button.
- Render close affordance for terminal tabs.

Update `tabIcon(tab)`:

- Return `terminal` for `tab.isTerminal`.

Update workspace switching:

- If active tab belongs to another workspace, fall back to a terminal tab from the new workspace only if the previous active tab was a terminal; otherwise preserve current behavior.
- Call `terminal:list` after joining a workspace if using reconnect retention.

### Socket Handlers

Add handlers in `static/app.js`:

- `socket.on('terminal:created', ...)`
- `socket.on('terminal:output', ...)`
- `socket.on('terminal:exit', ...)`
- `socket.on('terminal:closed', ...)`
- `socket.on('terminal:error', ...)`
- `socket.on('terminal:list', ...)`

For `terminal:output`, do not store all output in Vue state. Route output directly to the mounted `TerminalTab` component by ref. xterm owns scrollback.

If output arrives while a component is not mounted, keep a small pending buffer per terminal ID and flush it on mount. Limit this pending buffer to avoid unbounded memory growth.

### Styles

Add terminal-specific CSS to `static/style.css`:

- `.terminal-tab`
- `.terminal-toolbar`
- `.terminal-container`
- `.terminal-status`

The terminal container must:

- Fill available height.
- Have `min-height: 0`.
- Avoid nested cards.
- Use the app's panel/background tokens, while letting xterm control its inner colors.

---

## Backend Technical Design

### New Module

Add `server/terminal.py`.

Core structures:

```python
class TerminalSession:
    workspace_id: str
    terminal_id: str
    client_id: str
    owner_sid: str
    cwd: str
    pid: int
    master_fd: int
    process: subprocess.Popen
    reader_thread: threading.Thread
    status: str
    created_at: float
    last_seen_at: float
```

Add a `TerminalManager` owned by the Flask app config or module-level singleton.

Responsibilities:

- Create PTY sessions.
- Write input.
- Resize PTYs.
- Close sessions.
- Restart sessions.
- List sessions by workspace and client.
- Clean up exited or detached sessions.

### PTY Spawn

Use Python standard library:

- `pty.openpty()`
- `subprocess.Popen(..., stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, cwd=workspace_path, env=env, start_new_session=True)`
- `os.read(master_fd, chunk_size)` in a background thread
- `os.write(master_fd, data.encode(...))` for input
- `fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))` for resize

Close the slave FD in the parent after spawn.

Set environment:

```python
env = os.environ.copy()
env.update({
    "TERM": "xterm-256color",
    "COLORTERM": "truecolor",
    "BULLPEN_WORKSPACE": workspace_path,
})
```

Optional prompt nicety:

```python
env.setdefault("BULLPEN_TERMINAL", "1")
```

### Threading Compatibility

The current app uses Flask-SocketIO with websocket transport and Python threading-oriented dependencies. The terminal reader should use real OS threads and avoid eventlet-specific assumptions.

When emitting from reader threads, call:

```python
socketio.emit("terminal:output", payload, to=sid_or_room)
```

The prototype must validate that PTY reads do not block other Socket.IO traffic.

### Event Registration

Add terminal events to `server/events.py` or a dedicated registration function imported by it.

Each handler must:

- Reject MCP-authenticated clients.
- Resolve and validate `workspaceId`.
- Ensure workspace membership.
- Validate `terminalId`, `clientId`, `cols`, `rows`, and payload size.
- Use the terminal manager.

Avoid holding the global write lock around long-running PTY operations. Creation and manager map mutation need short critical sections; PTY reads/writes must not block task and worker events.

### Validation

Add validators in `server/validation.py`:

- `validate_terminal_id(value)`
- `validate_terminal_client_id(value)`
- `validate_terminal_size(cols, rows)`
- `validate_terminal_input(data)`

Rules:

- IDs: non-empty string, max 100 chars, UUID-like preferred.
- Input chunk: string, max 64 KiB.
- Output chunk: backend chunks at max 16 KiB.
- Cols: integer 20-300.
- Rows: integer 5-100.

### Cleanup

Server cleanup cases:

- Explicit `terminal:close`: send SIGHUP/SIGTERM to the process group, wait briefly, then SIGKILL if needed.
- Shell exits: close FD, remove or mark exited.
- Browser disconnect: mark detached and schedule cleanup after grace period, or terminate immediately for the minimal implementation.
- Workspace removed: terminate all terminal sessions for that workspace.
- Server shutdown: terminate all terminal sessions.

Use `os.killpg(pid, signal.SIGHUP)` when `start_new_session=True` is used.

---

## Security and Safety

This feature grants browser users command execution as the Bullpen server user. That is powerful and expected, but it must be explicit in implementation and review.

Required safeguards:

- Only authenticated browser sessions may use terminal events.
- MCP-authenticated clients must be rejected for all terminal events.
- Terminal sessions must be scoped by both `workspaceId` and owner identity (`request.sid` and preferably `clientId`).
- A browser client may only interact with its own terminals.
- Spawn `cwd` must be the resolved workspace path from the project manager, never a client-supplied path.
- Do not accept arbitrary shell command or cwd parameters in `terminal:create`.
- Enforce terminal count limits.
- Enforce input chunk size limits.
- Do not write terminal transcripts to `.bullpen/` by default.
- Do not expose terminal events to unauthenticated Socket.IO rooms.

Security note for documentation:

> The web terminal is equivalent to local shell access as the user running Bullpen. Only enable it where browser access to Bullpen is trusted.

---

## Accessibility

- Terminal tab button must have an accessible label.
- New terminal button must have an accessible label and tooltip.
- Status changes should be represented in text, not color only.
- The terminal pane should not trap browser focus permanently; users must be able to leave it with normal browser/tab navigation where xterm permits.
- Close/restart controls must be reachable by keyboard.

---

## Testing Plan

### Unit Tests

Backend:

- Terminal ID/client ID validation.
- Terminal size validation.
- Terminal manager rejects unknown workspace.
- Terminal manager enforces per-workspace and per-client limits.
- `terminal:create` rejects MCP-bound SID.
- `terminal:create` uses manager workspace path as cwd.
- `terminal:input` rejects oversized chunks.

### Integration Tests

Using Flask-SocketIO test client where practical:

- Create terminal, receive `terminal:created`.
- Send `echo bullpen-terminal-test\n`, receive matching output.
- Resize terminal and verify no error.
- Send `exit\n`, receive `terminal:exit`.
- Close terminal, receive `terminal:closed`.

PTY tests may need to be skipped on platforms without POSIX PTY support.

### Manual Browser QA

- Open a terminal in workspace A and run `pwd`; confirm it equals workspace A path.
- Open two terminals; confirm independent shell state by `cd` in one and `pwd` in the other.
- Switch tabs; terminal continues running.
- Run a streaming command such as `yes | head -1000`; UI remains responsive.
- Run `python3 -c "import time; print('start'); time.sleep(2); print('done')"`.
- Use `Ctrl+C` to interrupt `sleep 30`.
- Resize the browser; prompt and full-screen output reflow.
- Switch workspace; terminals from the previous workspace disappear from tab list.
- Close a running terminal; process is terminated.
- Disconnect/reconnect behavior matches chosen implementation.

---

## Implementation Outline

### Tranche 1: Prototype Spike

Goal: validate PTY + Flask-SocketIO behavior before full UI polish.

- Add xterm.js and FitAddon CDN assets.
- Add minimal `TerminalTab.js`.
- Add basic `server/terminal.py`.
- Add events: `terminal:create`, `terminal:input`, `terminal:resize`, `terminal:close`.
- Add one "Terminal" tab button.
- Confirm local shell works and UI remains responsive.

### Tranche 2: Multi-Terminal Tab Integration

- Add `terminalTabs` state in `static/app.js`.
- Add multiple terminal creation and close behavior.
- Add labels and close prompts.
- Scope tabs to active workspace.
- Add terminal status handling.

### Tranche 3: Lifecycle and Reconnect

- Add `clientId` in `sessionStorage`.
- Add `terminal:list`.
- Decide and implement either immediate disconnect cleanup or grace-period reconnect.
- Add workspace removal cleanup.
- Add shutdown cleanup.

### Tranche 4: Tests and Hardening

- Add validation tests.
- Add Socket.IO integration tests.
- Add terminal count limits.
- Add payload limits.
- Add final security review pass.

---

## Open Questions

1. Should the first implementation kill terminals immediately on browser disconnect, or invest in the 2-minute reconnect grace period?
2. Should terminal tabs be restored from `sessionStorage` after page refresh if the server still has live PTYs?
3. Should there be a config flag to disable the terminal feature for hosted deployments?
4. Should terminal creation be available from the command palette once the tab feature is stable?
5. Should service worker logs and web terminals share any future terminal-like component infrastructure, or remain separate?

---

## Recommended Defaults

- Library: xterm.js.
- Backend: Python PTY bridge over existing Socket.IO.
- Shell: `$SHELL`, fallback to zsh/bash/sh.
- CWD: active workspace path from project manager.
- Max terminals: 8 per workspace, 24 per browser client.
- Scrollback: 5000 lines.
- Disconnect behavior for first implementation: terminate on disconnect if reconnect retention complicates the spike; otherwise implement 2-minute grace with `clientId`.
- Transcript persistence: none.

