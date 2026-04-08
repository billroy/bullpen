# Feature: Live Agent Output & Worker Focus Mode

Status: **Planning**

## Problem

Agent execution is a black box. `proc.communicate()` in `workers.py:336` blocks until the agent finishes, then delivers all output at once. A 10-minute agent run produces zero feedback until it completes or times out. The worker card shows a static "working" pill with no indication of progress.

The best part of tools like claude.app is watching the session develop in real time -- seeing tool calls, file edits, and reasoning as they happen. Bullpen should offer the same degree of visibility.

## Overview

This feature adds two capabilities:

1. **Streaming backend** -- read agent stdout line-by-line and emit incremental socket events
2. **Worker Focus Mode** -- a full-screen live output view activated by clicking a working agent, rendered as a temporary tab

---

## 1. Streaming Agent Output (Backend)

### Current State

`_run_agent()` (`workers.py:319-358`) uses `proc.communicate(input=prompt, timeout=timeout)` which blocks the thread until the subprocess exits. Output is a single string delivered to `_on_agent_success` or `_on_agent_error`, then appended to the task body in one shot via `_append_output()` (`workers.py:548-570`).

The `_processes` dict stores `{(ws_id, slot_index): Popen}`. No running output buffer exists.

### Desired Behavior

Replace `proc.communicate()` with incremental line-by-line reading from stdout. Emit `worker:output` socket events as lines arrive, batched on a short interval to avoid flooding. Stderr is still collected in bulk (it's typically small -- just error messages).

### Changes Required

**`server/workers.py` -- `_run_agent()`:**

- Write the prompt to `proc.stdin`, then close stdin immediately (the agent reads the full prompt, then begins working)
- Replace `proc.communicate()` with a read loop:
  ```
  proc.stdin.write(prompt)
  proc.stdin.close()

  output_lines = []
  for line in proc.stdout:
      output_lines.append(line)
      emit line to frontend

  proc.wait(timeout=remaining)
  stderr = proc.stderr.read()
  ```
- Emit `worker:output` events via `_ws_emit()` carrying `{slot_index, lines, workspaceId}`
- Batch emissions: accumulate lines for up to 200ms, then emit a single event with a `lines` array to avoid per-line socket overhead
- Track timeout manually: record start time, check elapsed time periodically, `proc.kill()` if exceeded
- On completion, join all `output_lines` into the full stdout string and proceed to the existing `adapter.parse_output()` / `_on_agent_success` / `_on_agent_error` path unchanged

**`server/workers.py` -- `_processes` dict:**

- Expand stored value from just `Popen` to `{"proc": Popen, "output_buffer": [], "task_id": str}` so the frontend can request the current buffer when opening focus mode mid-run

**New socket events:**

| Event | Direction | Payload | Purpose |
|-------|-----------|---------|---------|
| `worker:output` | server -> client | `{workspaceId, slot, lines: [str]}` | Incremental output batch |
| `worker:output:request` | client -> server | `{workspaceId, slot}` | Request current buffer (for late join) |
| `worker:output:catchup` | server -> client | `{workspaceId, slot, lines: [str]}` | Full buffer so far (response to request) |

### Edge Cases

- **Agent writes to stderr interleaved with stdout**: Stderr is not streamed. It's read after process exit and included in the error path only. This matches current behavior.
- **Binary output or very long lines**: Cap individual line length at 10KB. Truncate with `[line truncated]`.
- **Agent produces no stdout** (e.g., writes directly to files): Focus mode shows an empty terminal with a "waiting for output..." message. The `files:changed` event at completion still works as today.
- **Multiple clients watching the same worker**: `worker:output` is emitted to the workspace room, so all connected clients receive it. Each client independently decides whether to display it.
- **Output buffer memory**: Cap at 100KB in the server-side buffer. Older lines are dropped from the buffer but still included in the final output written to the task body. The buffer is only for live display, not persistence.

---

## 2. Worker Focus Mode (Frontend)

### Current State

Clicking a working worker's card body fires `onBodyDblClick` (`WorkerCard.js:99-101`) which emits `select-task`, opening the `TaskDetailPanel` in the right side of the Kanban tab. This panel shows the task description and a static dump of agent output (extracted from the task body's `## Agent Output` section). There is no streaming display and the panel is small.

### Desired Behavior

Clicking a **working** worker (single click on the card body, not double-click) opens **Worker Focus Mode**: a temporary tab in the main tab bar that takes over the content area with a live, auto-scrolling terminal view of the agent's output.

### UI Design

**Tab bar**: `Kanban | Bullpen | Files | {WorkerName}` -- the worker's name appears as a fourth tab with a distinct style (e.g., pulsing dot indicator, or different text color) to signal it's a live session. Multiple focus tabs can be open simultaneously if the user clicks different workers.

**Focus view layout** (top to bottom):

```
+------------------------------------------------------------------+
| [Task Title]                              [Stop] [Minimize] [X]  |
| task type pill | priority pill | assigned to: Worker Name         |
+------------------------------------------------------------------+
| Task description (collapsed by default, expandable)              |
+------------------------------------------------------------------+
|                                                                  |
|  Live agent output stream                                        |
|  (monospace, dark background, auto-scrolling)                    |
|                                                                  |
|  > Reading file src/auth.py...                                   |
|  > Analyzing authentication flow...                              |
|  > Writing changes to src/auth.py...                             |
|  > Running tests...                                              |
|  > 12 tests passed                                               |
|  |  <-- cursor/blinking indicator when waiting for output        |
|                                                                  |
+------------------------------------------------------------------+
| Status: Working (2m 34s elapsed)              Output: 1,247 lines|
+------------------------------------------------------------------+
```

**Behavior:**

- **Auto-scroll**: Output area scrolls to bottom as new lines arrive. If the user scrolls up to read earlier output, auto-scroll pauses. Scrolling back to the bottom (or clicking a "Resume auto-scroll" button) re-enables it.
- **Text selection**: Output is selectable and copyable.
- **Stop button**: Sends `worker:stop` for this slot. Output area shows final lines, status changes to "Stopped".
- **Agent completes while watching**: Status bar updates to "Done" or "Failed". The tab remains open (doesn't auto-close) so the user can review the full output. A subtle toast confirms completion.
- **Close (X)**: Closes the focus tab and returns to the previously active tab. Does not stop the agent.
- **Minimize**: Returns to the previous tab but keeps the focus tab in the tab bar for quick return. The tab shows an activity indicator if new output arrives while minimized.
- **Late join**: User clicks a worker that's been running for 5 minutes. The frontend emits `worker:output:request`, receives the buffered output via `worker:output:catchup`, renders it, then appends new `worker:output` lines as they arrive.

### Entry Points

1. **Single-click on a working worker card body** in the Bullpen grid -- opens focus mode for that worker
2. **Click "Watch" in the worker context menu** (the right-click `...` menu) -- same effect
3. **Click a working worker's name in the left pane roster** -- opens focus mode

Non-working workers retain their current click behavior (configure modal, task selection, etc.).

### Changes Required

**New component: `static/components/WorkerFocusView.js`**

- Props: `worker`, `slotIndex`, `task`, `workspaceId`
- On mount: emit `worker:output:request` to get buffered output, subscribe to `worker:output` events filtered by slot
- Renders: task header, collapsible description, output terminal area, status bar
- Terminal area: `<pre>` with `overflow-y: auto`, dark background (`var(--bg-dark)`), monospace font
- Auto-scroll logic: track `scrollTop + clientHeight >= scrollHeight - threshold`, pause when user scrolls up
- Elapsed time: computed from `worker.started_at` (new field, see below) updated every second via `setInterval`
- On unmount: clean up interval, unsubscribe from events

**`static/app.js`:**

- New reactive state: `focusTabs: []` -- array of `{slotIndex, workspaceId, label}` for open focus tabs
- New state: `activeTabId` -- currently can be `"kanban"`, `"bullpen"`, `"files"`, or `"focus-{slot}"` for focus tabs
- Socket handler for `worker:output`: append lines to a per-slot reactive buffer `outputBuffers[slot]`
- Socket handler for `worker:output:catchup`: replace buffer contents
- When `layout:updated` arrives and a focused worker's state changes from "working" to "idle", update the focus tab's status but don't close it
- `openFocusTab(slotIndex)`: add to `focusTabs` if not already present, switch to it
- `closeFocusTab(slotIndex)`: remove from `focusTabs`, switch to previous tab

**`static/components/WorkerCard.js`:**

- Change click behavior when `worker.state === "working"`: single click on card body emits `open-focus` instead of or in addition to `select-task`
- Keep double-click for opening task detail (existing behavior) as fallback

**`static/components/BullpenTab.js`:**

- Handle `open-focus` event from WorkerCard, bubble up to app

**`static/components/TopToolbar.js` or tab bar area:**

- Render focus tabs in the tab bar alongside Kanban/Bullpen/Files
- Each focus tab shows worker name + activity dot
- Close button on each focus tab

**`server/workers.py`:**

- Add `started_at` timestamp to worker state when transitioning to "working" (in `start_worker()` around line 90)
- Include `started_at` in layout so the frontend can compute elapsed time

### Edge Cases

- **Worker finishes before focus tab opens**: `worker:output:catchup` returns the full buffer. Focus tab renders the complete output with "Done" status. No streaming needed.
- **Worker is stopped from focus mode**: Stop button emits `worker:stop`, output shows remaining lines from the killed process, status shows "Stopped".
- **Multiple focus tabs open**: Each independently subscribes to its own slot's output. Tab bar may get crowded -- limit to 3-4 focus tabs and show a warning if more are opened.
- **Workspace switch while focus tab is open**: Focus tabs are workspace-scoped. Switching workspace hides them (but doesn't destroy them). Switching back restores them.
- **Page refresh during active agent**: Output buffer is lost. Focus tab can be reopened and will show `worker:output:catchup` with whatever buffer the server still has. If the server restarted too, the buffer is gone -- the user sees output only after the agent completes (graceful degradation to current behavior).

---

## 3. Worker Card Output Preview (Enhancement)

### Current State

`WorkerCard.js:86-96` extracts the last 20 lines from the task body's `## Agent Output` section. This only updates when `task:updated` fires (i.e., after agent completion).

### Desired Behavior

While an agent is working, the worker card shows a **live 3-line preview** of the most recent output at the bottom of the card. This updates in real-time from the `worker:output` stream without requiring the user to open focus mode.

### Changes Required

- WorkerCard subscribes to the `worker:output` event (or reads from the shared `outputBuffers[slot]` reactive state)
- Display last 3 lines in a small `<pre>` at the bottom of the card, truncated with ellipsis
- CSS: muted text color, small monospace font, single-line-height, `overflow: hidden`
- When the agent is idle, this area is hidden (no output to show)

---

## Implementation Order

| Phase | Scope | Depends On |
|-------|-------|------------|
| **A** | Streaming backend: replace `proc.communicate()`, emit `worker:output`, buffer management | Nothing |
| **B** | Output buffers in app.js: reactive state, socket handlers, catchup | Phase A |
| **C** | WorkerFocusView component + tab integration | Phase A, B |
| **D** | Worker card live preview (3-line) | Phase B |
| **E** | Entry points: click handlers, context menu "Watch", roster click | Phase C |

Phases A+B are the foundation. Phase C is the main UI deliverable. Phase D is a polish enhancement. Phase E wires up all entry points.

## Verification

1. Start an agent on a long task (e.g., "review all files in this project")
2. While working, single-click the worker card -- focus tab should open with output streaming in real-time
3. Scroll up in the output area -- auto-scroll should pause; scroll to bottom to resume
4. Open a second browser tab -- it should be able to open the same focus view and see the same stream
5. Click Stop -- agent should terminate, output should show final lines, status should show "Stopped"
6. Let an agent complete while watching -- status should change to "Done", output should be complete, tab should stay open
7. Close the focus tab -- should return to previous tab, agent (if still running) should not be affected
8. Click a working worker while on the Kanban tab -- should switch to focus view
9. Refresh the page while an agent is working -- reopen focus should get catchup buffer
