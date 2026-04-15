# Cross-Project Isolation Fixup

**Status:** Specification — ready for implementation planning  
**Trigger:** Live Agent MCP bug — opening an agent in Project B returns Project A's tickets  
**Scope:** All multi-project isolation failures identified in the current codebase

---

## Root Cause Summary

The Live Agent chat subsystem was built without workspace context.  Every other
Socket.IO event in the app wraps its payload with `_wsData()` (which injects
`workspaceId: activeWorkspaceId.value`), but the three chat events — `chat:send`,
`chat:stop`, `chat:clear` — were never wired to that helper.

On the backend, `_resolve(data)` returns the `startup_workspace_id` when
`workspaceId` is absent.  The result: every Live Agent invocation, regardless of
which project is active in the browser, targets the first project that was open
when the server started.

The MCP `--bp-dir` argument is derived from the same `_resolve()` call, so the
agent's MCP server connects to Project A's socket room and reads Project A's
`.bullpen/` directory.  All ticket list/create/update calls go to the wrong
project.

A secondary issue: chat output events (`chat:output`, `chat:done`, `chat:error`)
are broadcast globally (`socketio.emit(...)`) rather than to the workspace room
(`socketio.emit(..., to=ws_id)`), so every connected browser sees every agent's
output, filtered only by `sessionId` on the client.

---

## MCP Multi-Project Architecture Analysis

This section documents the full picture of how MCP instances are scoped to
projects — and where that scoping currently breaks down.

### How MCP subprocesses work

Each `chat:send` event spawns a fresh MCP subprocess via `subprocess.Popen()` in
`_run_chat()` (`events.py:811`).  Background workers also spawn a fresh MCP
subprocess per agent execution (`workers.py:585`).  The subprocess receives a
temporary JSON config file that embeds `--bp-dir` pointing at the target
workspace's `.bullpen/` directory.

Crucially, MCP processes are **ephemeral**: connect → do work → disconnect.
This is a strength for isolation: no stale state lingers between invocations.
The weakness is that the correct `bp_dir` must be resolved accurately at spawn
time, because there is no mechanism to correct it later.

### How the MCP client discovers its workspace ID

When the MCP subprocess connects to the Bullpen server, the server sends a
`state:init` event for **every** registered workspace (not just the target one).
The MCP client in `mcp_tools.py` uses path matching to identify its workspace:

```python
if os.path.realpath(workspace) == self.workspace_path:
    self.workspace_id = workspace_id   # ← correct path, accept
    return
if self.workspace_id is None:
    self.workspace_id = workspace_id   # ← silent fallback: first state:init wins
```

**Race condition:** If the correct workspace's `state:init` arrives *after* any
other workspace's `state:init`, the MCP client silently adopts the wrong
`workspace_id`.  Since the server emits to all workspaces in list order, this is
deterministic today, but fragile — adding a workspace or changing list order can
silently redirect an MCP instance.

### Concurrent multi-project MCP usage

Background workers are keyed by `(ws_id, slot_index)`, so Project A's workers
and Project B's workers can run simultaneously without process-level collisions.
Each spawns its own MCP subprocess with its own `bp_dir`.

**The scoping gap is on the server side, not the process side.**  When an MCP
subprocess issues a `task:create` or `task:update` event, the handler calls
`_resolve(data)` which reads `workspaceId` from the payload — a value that comes
from the MCP client itself.  There is no server-side check that the socket's
claimed `workspaceId` matches the Socket.IO room it joined.  A mis-configured or
malfunctioning MCP client can write tickets into any workspace it can name.

The fix requires two changes working together:
1. The MCP client must resolve and use the correct `workspace_id` (path-match,
   no silent fallback).
2. The server's `task:create` / `task:update` handlers must assert that the
   emitting socket is a member of the target workspace room before processing.

### Worker MCP isolation requirement

Workers in Project A must never affect Project B's tickets, even when both are
running concurrently.  The current per-message subprocess architecture supports
this as long as `bp_dir` is set correctly, but it must be explicitly verified:

- The scheduler (`server/scheduler.py`) must carry `ws_id` through triggered
  executions (currently does so via explicit parameter — confirmed).
- The `_run_agent()` function threads `ws_id` through to all socket emissions
  (confirmed).
- The MCP subprocess receives `bp_dir` via config generation (confirmed), not
  as a run-time argument the agent could override.

The remaining vulnerability is the server-side room membership check described
above.

---

## Architecture Decisions

The following design questions from the original draft have been resolved:

**1. Tab lifecycle on project switch**  
Decision: **Live Agent tabs are bound to the project they were created in.**
A tab opened in Project A continues targeting Project A even after the user
switches to Project B.  The tab label should display the project name to make
the binding visible.  Switching projects does not close existing agent tabs.

**2. Single-user vs. multi-user security model**  
Bullpen is single-user, but all P2 security items should be implemented anyway.
The effort is low and the protections guard against bugs as much as malicious use.

**3. MCP reconnection on project switch**  
Being in a project means being in that project for all purposes, including the
MCP.  Each tab carries its creation-time `workspaceId` through to every
subsequent MCP invocation.  Because MCP is per-message and stateless, passing
the correct `bp_dir` each time is sufficient — no persistent reconnect logic
is required.  Background workers in other projects use their own project-local
MCP concurrently; this must continue to work correctly.

---

## Prioritized Work Items

### P0 — Blocks all Live Agent multi-project use (fix together, one PR)

**P0-A: Add `workspaceId` to all outgoing chat events (frontend)**  
File: `static/components/LiveAgentChatTab.js`

The component has no reference to `activeWorkspaceId`.  Changes required:

- Add `workspaceId` to the `chatTabs` entries created in `addLiveAgentTab()`
  in `app.js`:
  ```js
  chatTabs.push({ id, label, sessionId: _newChatSessionId(),
                  workspaceId: activeWorkspaceId.value });
  ```
- Pass `workspaceId` as a prop to `<LiveAgentChatTab>` in the template.
- Display the originating project name in the tab label so the user can see
  which project each agent is operating in.
- In the component, attach `workspaceId` to all three emits:
  ```js
  s.emit('chat:send',  { sessionId, provider, model, message, workspaceId: this.workspaceId });
  s.emit('chat:stop',  { sessionId, workspaceId: this.workspaceId });
  s.emit('chat:clear', { sessionId, workspaceId: this.workspaceId });
  ```

---

**P0-B: Scope chat output events to workspace room (backend)**  
File: `server/events.py`, `_run_chat()` function

`_run_chat` already receives `ws_id` as a keyword argument (line 784), but the
`socketio.emit()` calls inside it never use it.  Every call must become:
```python
socketio.emit("chat:output", {"sessionId": session_id, "lines": to_emit}, to=ws_id)
socketio.emit("chat:done",   {"sessionId": session_id}, to=ws_id)
socketio.emit("chat:error",  {"sessionId": session_id, "message": ...}, to=ws_id)
```
Affected lines: 872, 900, 914, 922, 933, 940, 996, 1001.

Note: `ws_id` can be `None` if `_resolve()` falls back to `startup_workspace_id`
and that workspace has been deleted.  Add a guard and emit a `chat:error` instead
of attempting a `to=None` emit.

---

### P1 — Correctness issues that break expected behavior

**P1-A: Live Agent tabs not scoped to a project (frontend)**  
File: `static/app.js`, `addLiveAgentTab()` / `chatTabs`  
Currently `chatTabs` entries have `{id, label, sessionId}` — no `workspaceId`.  
Fix: add `workspaceId` and the project display name as described in P0-A.

**P1-B: `focusTabs` worker-output tabs also not cleared on project switch**  
File: `static/app.js`, `switchWorkspace()` / `focusTabs`  
`focusTabs` entries do store `workspaceId`, but `switchWorkspace()` does not
filter them.  A worker output tab from Project A remains visible when the user
switches to Project B.  Fix: on workspace switch, hide or close tabs from other
workspaces, with a visual indicator if an agent from another project is still
running.

**P1-C: MCP workspace detection silent fallback**  
File: `server/mcp_tools.py`, `_on_state_init()` (around line 252)  
If path matching fails, the code falls back to accepting the first `state:init`
received.  On connect, the server sends a `state:init` for every registered
workspace — if list ordering places a different project first, the MCP client
silently adopts the wrong workspace.  Fix: remove the silent fallback entirely.
If path matching fails for all received `state:init` events, log a warning to
`sys.stderr` and leave `workspace_id` as `None`.  All subsequent tool calls
must return a clear error rather than operating on an unintended project.

---

### P2 — Security and authorization

**P2-A: No server-side cross-workspace authorization on task writes**  
File: `server/mcp_tools.py`, `create_ticket()`, `update_ticket()`  
The `workspaceId` used in MCP tool call payloads is set at connection time by
the MCP client itself and never re-validated by the server.  The `task:create`
and `task:update` handlers call `_resolve(data)`, which reads `workspaceId`
from the payload — but that value is supplied by the (potentially mis-configured)
MCP client.  

Fix: in `on_task_create` and `on_task_update`, assert that the emitting socket
is a member of the target workspace's Socket.IO room before processing the
request.  Flask-SocketIO exposes `rooms(request.sid)` for this check.  Reject
the request with an error if the socket is not in the claimed workspace room.
This closes the path where a mis-configured worker in Project A could write
tickets into Project B.

**P2-B: Weak chat session IDs**  
File: `static/components/LiveAgentChatTab.js`, `_generateChatSessionId()`  
Session IDs incorporate `Date.now()`, which is predictable.  Fix: use
`crypto.randomUUID()`.  After P0-B lands, output is room-scoped, substantially
reducing the practical impact — but the weak IDs are trivially fixable.

**P2-C: Global `projects:updated` broadcast exposes project list**  
File: `server/app.py`, lines 626, 764–765  
`projects:updated` is broadcast to all connected sockets, leaking project names
and paths.  For a single-user Bullpen this is benign, but fix it anyway: scope
the broadcast to a "global" room that only authenticated sockets join, consistent
with the room-scoped pattern used everywhere else.

---

### P3 — Reliability and maintainability

**P3-A: Global `_chat_sessions` dict leaks memory indefinitely**  
File: `server/events.py`, lines 773–778  
Chat sessions are removed only on explicit `chat:clear`.  Abandoned sessions
persist forever.  Fix: add a TTL-based eviction (purge sessions idle for more
than 24 hours) or clean up on socket disconnect.

**P3-B: `chat:send` handler missing `workspaceId` validation**  
File: `server/events.py`, `on_chat_send()` line 1019  
After P0-A lands, `workspaceId` will be present in the payload.  Add explicit
validation: if the resolved `ws_id` does not match any known workspace, return a
`chat:error` immediately rather than silently falling back to the startup
workspace.

**P3-C: Inconsistent `projects:updated` scoping vs. `project:removed`**  
File: `server/app.py`, line 763  
`project:removed` is broadcast globally; `state:init` goes correctly to
`to=ws.id`.  Unify the pattern: all workspace-scoped events must use
`to=ws_id`.  Only server-wide events (shutdown notices, etc.) should broadcast
globally.

**P3-D: `_resolve()` silent fallback to startup workspace**  
File: `server/events.py`, `_resolve()` function  
When `workspaceId` is absent from a payload, `_resolve()` silently falls back to
`startup_workspace_id`.  After P0 lands this should not happen for chat events,
but it remains a systemic risk for any future event handler.  Fix: log a warning
at the `_resolve()` call site whenever the fallback fires, so unexpected cases
become visible in server logs.  (Full removal of the fallback is a larger change;
the log warning is a low-risk safety net in the interim.)

---

## Testing Requirements

The existing test suite has no coverage of the chat/Live Agent subsystem.  The
following tests must land with or before P0:

**Required (block P0 landing):**

1. **`_resolve()` unit test** — call with `workspaceId` present and absent;
   assert correct `ws_id` and `bp_dir` returned in the first case, and that the
   fallback fires (and logs) in the second.

2. **`chat:send` routing integration test** — send a `chat:send` event with a
   specific `workspaceId`; assert that `_run_chat()` is invoked with the
   matching `bp_dir`, not `startup_workspace_id`'s `bp_dir`.

3. **Room-scoped output test** — after P0-B, emit a mock `chat:output` during a
   chat session and assert it is received only by sockets in the target
   workspace room, not by sockets in a different workspace room.

4. **Live agent end-to-end (auth proof)** — spawn a real MCP subprocess with a
   valid `mcp_token`, have it issue a `list_tickets` call, and assert it returns
   tickets from the correct project.  This is the definitive proof that the auth
   path, workspace resolution, and MCP tool routing all work together.  Without
   this test, P0 is unverifiable beyond manual inspection.

**Recommended (P1 release):**

5. **Concurrent multi-project worker test** — start workers in two different
   workspaces simultaneously; assert that each worker's MCP subprocess creates
   tickets only in its own workspace and that neither workspace sees the other's
   ticket events.

6. **MCP workspace detection test** — construct a `BullpenClient` with a known
   `bp_dir`, feed it synthetic `state:init` events for two workspaces in both
   orderings, assert it locks onto the correct one in both cases, and returns an
   error (not silently falls back) when no path matches.

---

## Summary Table

| ID    | Severity | Component       | Description                                              |
|-------|----------|-----------------|----------------------------------------------------------|
| P0-A  | Critical | Frontend        | `chat:send/stop/clear` missing `workspaceId`             |
| P0-B  | Critical | Backend         | `chat:output/done/error` broadcast globally, not to room |
| P1-A  | High     | Frontend        | Live Agent tabs not workspace-scoped                     |
| P1-B  | High     | Frontend        | Worker focus tabs not filtered on project switch         |
| P1-C  | High     | Backend (MCP)   | MCP workspace detection silent fallback                  |
| P2-A  | Medium   | Backend (MCP)   | No server-side cross-workspace authorization on writes   |
| P2-B  | Medium   | Frontend        | Weak session ID generation (predictable)                 |
| P2-C  | Medium   | Backend         | `projects:updated` leaks project list to all sockets     |
| P3-A  | Low      | Backend         | Unbounded `_chat_sessions` memory growth                 |
| P3-B  | Low      | Backend         | Missing `workspaceId` validation in `on_chat_send`       |
| P3-C  | Low      | Backend         | Inconsistent room-scoping across project events          |
| P3-D  | Low      | Backend         | `_resolve()` silent fallback produces no log warning     |
