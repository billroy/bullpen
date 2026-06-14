# Bullpen Playwright Suite Prospectus

## Status

Prospectus, detailed test plan, and implementation proposal for a comprehensive
browser-driven Playwright suite for Bullpen.

Scope is limited to the main Bullpen application. Bullpen Manager is explicitly
out of scope for this document.

## Executive Summary

Bullpen already has broad backend, Socket.IO, persistence, and frontend
structure coverage through pytest. That suite is valuable, fast, and should
remain the primary guardrail for business logic. The gap is the real browser
surface: menus, drag/drop, modal focus, layout, theme rendering, live Socket.IO
state, tab behavior, contenteditable/editor behavior, terminal rendering,
multi-client synchronization, and flows where a user can see a control but
cannot actually complete the job.

The proposed Playwright suite should become Bullpen's closed-loop product
quality layer. It should answer:

- Can a user complete the core Bullpen workflows with only the UI?
- Do controls that are visible actually perform the promised action?
- Does the UI stay synchronized with server state across reconnects,
  workspace switches, and multiple browser tabs?
- Do advanced workers behave consistently across create, edit, run, drop,
  pause, schedule, transfer, and delete paths?
- Do high-risk surfaces such as terminal, file editing, auth, and worker
  execution fail safely and explain themselves?
- Does the app remain usable across dark/light themes and desktop/tablet/mobile
  viewport classes?

The recommended implementation is a Python Playwright suite run by pytest, not
a separate Node test stack. Bullpen is a Python/Flask/Socket.IO app with CDN Vue
and no frontend build step; pytest already owns fixture isolation, mock
adapters, temporary workspaces, and app lifecycle. Python Playwright keeps the
suite in that ecosystem while still exercising real Chromium, Firefox, and
WebKit where needed.

## Explicit Non-Scope

This suite does not cover Bullpen Manager.

Do not include:

- `/manager` routes.
- `static/manager/index.html`.
- `static/manager/manager.js`.
- `static/manager/manager.css`.
- `server/manager.py` behavior except where the main Bullpen app imports shared
  process state that must be stubbed for startup.
- Manager project dashboards, deployment management, global launchers, or
  Manager-specific auth/session behavior.

If Bullpen Manager later needs browser coverage, create a separate document and
suite with its own fixtures and risk model.

## Goals

1. Exercise Bullpen as a user experiences it, in a real browser.
2. Use server-backed APIs and Socket.IO helpers for setup and assertions so test
   state remains live and synchronized.
3. Avoid direct `.bullpen/tasks` writes in tests unless a test is specifically
   about startup reconciliation or corrupted persisted state.
4. Keep the normal developer loop fast by dividing tests into smoke, feature,
   cross-browser, visual, and stress groups.
5. Use stable selectors and page objects so UI refactors do not turn every test
   into a rewrite.
6. Make failures highly actionable: a failing test should say which user flow
   broke, capture trace/video/screenshot, and identify the server event or
   persisted state that disagreed with the UI.
7. Cover every user-facing control on the main Bullpen surface at least once.
8. Keep tests deterministic by using temporary workspaces, mock agent adapters,
   fake shell commands, and controlled time where possible.

## Current Coverage Baseline

Bullpen has strong lower-level coverage:

- Backend pytest coverage for app creation, events, auth, task CRUD,
  persistence, workers, shell workers, service workers, profiles, teams,
  worktrees, terminal, MCP, file APIs, commit APIs, validation, and deployment
  helpers.
- Socket.IO end-to-end tests for create/assign/run flows.
- Many frontend tests that inspect component source and guard structural
  behavior.
- One optional Python Playwright regression for the notification worker dialog
  and run menu.

Those tests should remain. The Playwright suite should not duplicate every
backend assertion. It should focus on browser integration and user-observable
completion.

## Recommended Stack

Use:

- `pytest`.
- `playwright.sync_api` or `playwright.async_api`; prefer sync API initially for
  consistency with the existing notification test.
- Python fixtures that launch Bullpen on a free localhost port with a temporary
  workspace and isolated `HOME`.
- Mock agent adapters and fake command executables where worker execution must
  be deterministic.
- Browser traces, screenshots, and videos on failure.
- `pytest` markers for test grouping:
  - `playwright_smoke`
  - `playwright_core`
  - `playwright_workers`
  - `playwright_files`
  - `playwright_terminal`
  - `playwright_auth`
  - `playwright_visual`
  - `playwright_cross_browser`
  - `playwright_slow`

Avoid:

- A permanent Node/npm test harness unless Bullpen later adopts a frontend build
  pipeline.
- Stock Playwright scaffold tests.
- Tests that reach external websites.
- Tests that require real Claude, Codex, Gemini, OpenCode, GitHub, or networked
  model services.

## Proposed Directory Layout

```text
tests/playwright/
  conftest.py
  fixtures.py
  server.py
  selectors.py
  state.py
  pages/
    app.py
    auth.py
    tickets.py
    workers.py
    worker_modal.py
    files.py
    terminal.py
    live_agent.py
    projects.py
  test_smoke.py
  test_auth.py
  test_tickets.py
  test_columns.py
  test_workers_core.py
  test_worker_types.py
  test_worker_scheduling.py
  test_worker_handoff.py
  test_notification_worker.py
  test_shell_worker.py
  test_service_worker.py
  test_files.py
  test_terminal.py
  test_live_agent.py
  test_commits_stats.py
  test_projects.py
  test_teams.py
  test_realtime_sync.py
  test_theme_responsive.py
  test_accessibility.py
  test_resilience.py
```

Support files:

```text
tests/fixtures/playwright/
  fake_agent.py
  fake_shell_worker.py
  sample_repo/
  sample_files/
  auth_env_templates/
```

The existing `tests/test_notification_worker_playwright.py` can be migrated
into this layout once the shared fixtures exist.

## Test Harness Architecture

### Server Fixture

Provide a `bullpen_server` fixture that:

1. Creates a temporary workspace.
2. Creates an isolated temporary `HOME`.
3. Selects a free `127.0.0.1` port.
4. Starts `python3 bullpen.py --workspace <tmp> --host 127.0.0.1 --port <port>
   --no-browser`.
5. Waits for `/` to return `200` or `/login` when auth is enabled.
6. Captures stdout/stderr to a per-test artifact file.
7. Stops the server, scheduler, terminal sessions, service workers, and worker
   processes in teardown.

The fixture should skip with a clear message when local port binding is not
permitted by the current sandbox.

### Browser Fixture

Provide `page` and `context` fixtures configured for:

- Default viewport: `1440x1000`.
- Locale: `en-US`.
- Timezone: local test timezone unless a test needs a fixed value.
- Reduced motion: configurable for animation-sensitive tests.
- Trace on failure.
- Screenshot on failure.
- Video on failure for slow/full runs.

Cross-browser jobs should run Chromium on every push and Firefox/WebKit on
nightly or pre-release runs. Most tests should be written browser-neutral, but
terminal and Web Speech-related flows may be Chromium-only if browser support
is uneven.

### State Fixture

Provide a `bullpen_api` or `bullpen_socket` fixture that can create test state
through the same server-backed paths the app uses:

- Create tickets.
- Update tickets.
- Add/configure workers.
- Add columns.
- Save teams.
- Switch workspaces.
- Wait for server events.

Use this for setup when the test is not specifically about the setup UI. For
example, a worker context-menu test can create the worker by Socket.IO and then
use Playwright to verify menu behavior. A ticket-create UI test should create
the ticket through the UI.

### Page Objects

Use small page objects around stable UI regions:

- `BullpenApp`: navigation, tabs, toast assertions, theme, reconnect.
- `TicketsPage`: kanban/list view, quick create, task cards, detail panel.
- `WorkersPage`: grid cells, worker cards, context menus, queues, focus tabs.
- `WorkerConfigModal`: create/edit worker forms for every worker type.
- `FilesPage`: tree, preview, editor, find/replace, save/download.
- `TerminalPage`: terminal tab lifecycle, input, resize, close confirmation.
- `LiveAgentPage`: chat tabs, provider selectors, send/stop, transcript ticket.
- `ProjectsPage`: project switcher, clone/register flows when locally
  mockable.

Page objects should not hide assertions. They should encapsulate locating and
performing user actions, while tests still describe expected outcomes plainly.

### Selector Strategy

Add stable attributes for high-value controls:

```html
data-pw="ticket-card"
data-pw="worker-card"
data-pw="worker-menu-run"
data-pw="worker-config-save"
data-pw="task-detail-save"
data-pw="files-editor-save"
```

Use accessible roles and names wherever they are already stable. Add `data-pw`
for controls whose visible text varies by theme, profile, status, workspace, or
icon-only rendering.

Do not use brittle CSS chains except when the test is explicitly about layout
or styling.

### Assertions

Every test should pair UI assertions with one durable state assertion when
possible:

- UI shows the ticket in the expected column.
- Socket/API state says the ticket has the expected status.
- Persisted task state was updated by the server.
- Worker queue count matches layout state.
- Toast text appears and disappears.
- No unexpected browser console errors occurred.

This prevents false confidence where a visual control changes but server state
does not, or server state changes but the UI remains stale.

## Detailed Test Plan

### 1. Smoke And Boot

Purpose: prove the app starts and the primary shell is usable.

Tests:

- Boot unauthenticated Bullpen at `/`.
- Verify top toolbar renders, active project name is visible, default tabs are
  present, and Socket.IO connects.
- Verify the default Tickets tab renders Inbox/Review/Done or configured
  columns.
- Switch through Tickets, Workers, Files, Stats, Commits, and Live Agent tabs.
- Reload the page and verify state rehydrates.
- Open the app in a second browser context and verify both clients receive
  `state:init`.
- Confirm `/manager` is not visited and no Manager bundle is loaded by the
  Bullpen suite.

### 2. Authentication

Purpose: verify local auth gates the main app and preserves session behavior.

Tests:

- Auth disabled: `/` loads directly, `/login` is not required.
- Auth enabled: unauthenticated `/` redirects to `/login`.
- Login succeeds with configured credentials and lands on the requested `next`
  path.
- Login failure shows an error without leaking which field failed.
- Logout clears the session and redirects to login.
- XHR and Socket.IO calls from unauthenticated contexts are rejected.
- Static assets required by login load without an authenticated session.
- Session survives page reload and server restart when the same secret is used.
- Network-exposed bind refusal remains covered by backend tests; browser suite
  only needs the user-visible login flow.

### 3. Ticket Creation And Editing

Purpose: cover the daily ticket lifecycle through UI controls.

Tests:

- Quick-create a ticket from the left pane.
- Open the full create modal and create each ticket type.
- Set priority, tags, title, and markdown body.
- Validate required/invalid fields and escaped rendering of HTML-like input.
- Open a ticket detail panel from a card.
- Edit title, tags, priority, type, and description.
- Save with button and with Cmd/Ctrl+Enter.
- Cancel edit and verify no state change.
- Copy ticket ID where the UI exposes that action.
- Verify markdown preview/source behavior if present.
- Verify detail panel remains read-only when opened from archived/list contexts
  that are intended to be read-only.
- Verify toast/error handling for oversized title/body using controlled server
  rejection.

### 4. Kanban Board

Purpose: cover drag/drop and column state in a real browser.

Tests:

- Drag a ticket between columns and assert server status update.
- Drag a ticket from Inbox to Review and Done.
- Reorder tickets within a column when supported.
- Verify priority-aware ordering is reflected visually.
- Add, rename, reorder, and delete columns through the column manager.
- Verify column icon/color controls if present.
- Verify missing-status tickets render in a safe fallback column.
- Verify ticket cards do not overlap at desktop/tablet/mobile widths.
- Verify scroll behavior on large columns and long ticket titles.
- Verify archived tickets leave the live board and appear in archived scope.
- Verify drag cancel leaves state unchanged.

### 5. Ticket List View

Purpose: cover the dense tabular ticket workflow.

Tests:

- Switch from Kanban to List view and back.
- Sort by title, status, priority, created time, and token fields.
- Filter by status, priority, type, and full-text search.
- Open detail from a list row.
- Verify created timestamp formatting and stable ordering.
- Verify live/archived/all scopes.
- Verify list count badge matches filtered rows.
- Verify long titles and tag sets remain readable without layout overflow.

### 6. Worker Grid Basics

Purpose: cover the worker grid as an interactive canvas.

Tests:

- Switch to Workers tab.
- Add a worker from an empty grid cell.
- Verify profile picker, default worker naming, and worker card rendering.
- Edit worker name, expertise, profile, provider, model, trust/approval mode,
  auto-commit, auto-PR, worktree, retry, and disposition controls.
- Save, reopen, and verify values round-trip.
- Duplicate, copy, export, delete, and cancel delete from the worker menu.
- Move a worker to another grid cell.
- Select multiple workers and verify selection handles.
- Verify group context menu scopes: this worker, connected group, selected
  workers.
- Verify worker minimap opens/collapses and navigates large grids.
- Verify worker card queue count, status readout, and vertical expansion.
- Verify menu positioning at viewport edges.

### 7. Worker Assignment And Run Lifecycle

Purpose: make sure visible worker controls cause actual work.

Tests:

- Create a ticket, drag it onto a worker, verify queue assignment.
- Use worker menu Run and verify queued ticket starts.
- Use Run on an empty runnable worker and verify synthetic ticket behavior for
  worker types that support it.
- Pause a worker and verify automation stops while manual affordances behave
  according to spec.
- Pause all worker automation and verify UI and server enforcement agree.
- Resume worker and verify queued work can proceed.
- Verify focus view opens for a running worker and streams output.
- Verify completion routes to Review, Done, Blocked, or pass direction.
- Verify failure routes to Blocked after configured retries.
- Verify stop/cancel controls if available.
- Verify toasts for invalid run attempts.
- Verify queue count changes in both worker card and left-pane roster.

### 8. AI Agent Workers

Purpose: cover provider worker UI without requiring real provider CLIs.

Use fake adapters or fake executables to simulate Claude, Codex, Gemini, and
OpenCode.

Tests:

- Configure each provider type and model selector.
- Verify provider availability states and disabled controls.
- Run a task with a mock successful output.
- Run a task with mock failure output and retry behavior.
- Verify structured stream parsing appears in focus view.
- Verify token usage metadata renders in ticket detail/list/stats.
- Verify transcript/log capture appears on the ticket where expected.
- Verify approval/trust modes are passed through to backend config.
- Verify missing executable/auth states display clear UI affordances.

### 9. Shell / Script Workers

Purpose: cover shell workers as a deterministic local execution type.

Tests:

- Create shell worker.
- Configure command, working directory, environment variables, ticket passing
  mode, timeout, and disposition.
- Run with `stdin-json`, `env-vars`, and `argv-json`.
- Verify stdout/stderr rendering and route on exit `0`.
- Verify exit `78` blocks without retry.
- Verify nonzero exit retries and then blocks.
- Verify stdout JSON can update ticket fields and append body text.
- Verify invalid JSON shows a clear error and follows documented fallback.
- Verify command examples load and insert correctly.
- Verify unsafe/invalid command config validation is visible.

### 10. Service Workers

Purpose: cover long-running workspace processes.

Tests:

- Create service worker and configure command, env, health check, port, and
  restart policy.
- Start service and verify status transitions to starting/running.
- Verify logs stream into service output view.
- Verify health check success and failure states.
- Restart service from menu.
- Stop service and verify process cleanup.
- Drop a ticket onto a service worker and verify documented trigger behavior.
- Verify service state survives page reload and reconciles on server restart.
- Verify Procfile import/discovery if present.

### 11. Marker Workers

Purpose: cover no-op and pass-through workers.

Tests:

- Create marker worker with label, notes, color/icon, and pass behavior.
- Drop a ticket and verify no execution occurs.
- Verify pass-through routes the ticket as configured.
- Verify marker worker is distinguishable from runnable workers.
- Verify Run is absent or disabled according to spec.
- Verify marker worker survives duplicate/export/copy/move operations.

### 12. Notification Workers

Purpose: prevent recurrence of the "visible but inert" class of bug.

Tests:

- Create notification worker from UI.
- Exercise every dialog control:
  - toast enable/disable
  - toast template
  - toast severity
  - toast duration
  - speech enable/disable
  - speech template
  - engine
  - voice hint
  - rate
  - pitch
  - sound enable/disable
  - sound preset
  - repeats
  - gap
  - volume
  - flash enable/disable
  - flash steps add/remove/edit
  - opacity
  - cooldown
  - dedupe window
  - trigger mode
  - watched column
  - trigger time
  - repeat daily
  - interval minutes
  - disposition
- Save, reopen, and assert every value round-trips.
- Manual Run with queued ticket fires notification and routes ticket.
- Manual Run with empty queue creates synthetic ticket and routes it.
- On-drop fires notification and routes dropped ticket.
- On-queue claims watched-column ticket and fires once.
- At-time and interval modes can be tested with controlled scheduler hooks or
  shortened intervals.
- Verify reduced-motion and audio-disabled browser settings do not break the
  configuration path.
- Verify unsupported Web Speech/audio APIs degrade gracefully.

### 13. Worker Scheduling

Purpose: cover time-based activation without slow wall-clock tests.

Tests:

- Configure manual, on-drop, on-queue, at-time, and interval triggers.
- Verify UI enables only the fields relevant to the selected trigger.
- Verify invalid time and interval values show errors.
- Use backend test hooks or monkeypatched scheduler time to trigger at-time and
  interval workers quickly.
- Verify automation pause suppresses scheduled starts.
- Verify scheduled empty queue behavior matches each worker type's spec.
- Verify scheduler state survives page reload and server restart.

### 14. Worker Handoff And Routing

Purpose: verify pass-connected workflows.

Tests:

- Connect workers left/right/up/down using grid handles.
- Configure disposition to Review, Done, Blocked, and pass directions.
- Run a ticket through a two-worker chain.
- Run through a branching grid where one pass direction is missing and verify
  graceful fallback/error.
- Verify pass tooltip and visual connectors update.
- Verify deleting a connected worker updates connectors and menus.
- Verify group copy/move preserves or intentionally rewrites connections.

### 15. Teams And Profiles

Purpose: cover saved worker configurations.

Tests:

- Save current grid as a team.
- Load a team and verify workers, positions, and configs.
- Rename/delete teams if UI supports it.
- Verify profile picker lists built-in profiles.
- Create/customize a profile if the UI supports it.
- Verify profile expertise appears in worker config and tooltips.
- Verify unconfigured-worker profile path.

### 16. Files Tab

Purpose: cover file browser/editor behavior in real browser APIs.

Tests:

- Browse workspace tree.
- Open text, markdown, image, PDF, and HTML files.
- Edit and save a text file.
- Verify dirty state and close/reload prompts.
- Find/replace in editor.
- Preview markdown with source-mode syntax highlighting.
- Preview HTML in sandbox and verify scripts are constrained as specified.
- Download a file.
- Click an HTML file and verify default-browser/open behavior is represented by
  the UI or a mocked server endpoint.
- Verify path traversal and hidden-file restrictions through user-visible
  errors.
- Verify large file handling.
- Verify `.bullpen/` browsing behavior matches spec.

### 17. Terminal Tabs

Purpose: cover xterm.js integration and PTY lifecycle.

Tests:

- Open a terminal tab.
- Verify prompt/output appears.
- Type a command and verify output.
- Resize viewport and verify terminal resize event is sent.
- Open multiple terminal tabs and switch between them.
- Enforce per-workspace terminal tab limit.
- Restart terminal.
- Close idle terminal.
- Close running terminal and verify confirmation.
- Verify terminal cleanup on browser disconnect.
- Verify terminal tab is scoped to active workspace.
- Verify unauthenticated users cannot open terminal when auth is enabled.

### 18. Live Agent Chat

Purpose: cover chat UI without real provider services.

Use fake provider backends or mocked Socket.IO responses.

Tests:

- Open Live Agent tab.
- Select provider/model.
- Send message and stream response.
- Stop generation.
- Add second chat tab.
- Close chat tab but keep at least one tab per workspace.
- Switch workspaces and verify chat tab scoping.
- Verify chat transcript creates or updates a ticket as documented.
- Verify provider unavailable state.
- Verify error toast when provider fails.
- Verify long messages and code blocks render without layout breakage.

### 19. Commits And Stats Tabs

Purpose: cover read-only dashboards.

Tests:

- Initialize a temporary git repo with commits.
- Open Commits tab and verify commit rows.
- Open diff modal and verify patch content.
- Verify copy/open actions if present.
- Open Stats tab with seeded token usage.
- Verify provider/model breakdown, totals, empty state, and refresh behavior.
- Verify charts/tables fit in light/dark themes and narrow widths.

### 20. Projects / Multi-Workspace

Purpose: cover the main Bullpen multi-project surface, not Bullpen Manager.

Tests:

- Register additional local workspace through main app UI if available.
- Switch active project.
- Verify each workspace has independent tickets, workers, files, chats, and
  terminal tabs.
- Verify unseen activity badges update when background workspace changes.
- Copy worker to another workspace.
- Move worker to another workspace.
- Copy/move selected worker group to another workspace.
- Verify profile copy option.
- Verify project name visibility in toolbar and left pane.
- Verify clone-from-Git UI using a local bare repo fixture, not a network repo.

### 21. Real-Time Multi-Client Sync

Purpose: prove Bullpen's Socket.IO state model works in browsers.

Tests:

- Open two browser contexts to the same workspace.
- Create ticket in one, verify it appears in the other.
- Edit ticket in one, verify detail panel updates in the other.
- Drag ticket in one, verify column move in the other.
- Add/configure worker in one, verify worker card updates in the other.
- Run worker in one, verify status/focus output in the other.
- Switch project in one and verify the other remains on its active project.
- Disconnect/reconnect one client and verify missed state is reconciled.
- Verify toasts are scoped correctly and do not duplicate excessively.

### 22. Themes, Layout, And Responsive Behavior

Purpose: prevent UI regressions that structural tests cannot see.

Tests:

- Toggle dark/light theme and verify persistence.
- Exercise primary flows under both themes for smoke subset.
- Verify all modals fit at `1440x1000`, `1024x768`, `768x1024`, and a mobile
  narrow viewport where supported.
- Verify worker menu and task menus position inside viewport.
- Verify left-pane resize, min/max width, and touch scrolling guard.
- Verify no text overlap in worker cards, task cards, toolbar, menus, and modal
  buttons.
- Verify reduced-motion setting disables or softens motion-heavy effects.
- Verify high-contrast-ish screenshots for key views if visual snapshots are
  adopted.

### 23. Accessibility And Keyboard

Purpose: keep the app usable without mouse-only assumptions.

Tests:

- Tab through toolbar, left pane, task cards, worker cards, menus, and modals.
- Verify focus trap inside modals.
- Escape closes modals/menus where expected.
- Cmd/Ctrl+Enter saves where documented.
- Enter/Space activates buttons and menu items.
- ARIA names exist for icon-only buttons.
- Drag/drop alternatives exist or gaps are documented.
- Run axe-core smoke checks on stable pages if dependency policy allows it.

### 24. Security-Visible Browser Behavior

Purpose: catch browser-side failures around untrusted content.

Tests:

- Ticket title/body containing HTML renders as text or sanitized markdown.
- File preview refuses path traversal.
- HTML preview is sandboxed as specified.
- Login CSRF/session failure surfaces correctly.
- Socket.IO origin/auth rejection redirects or shows a clear error.
- Terminal is unavailable without auth when auth is enabled.
- File editor does not write outside workspace.
- Markdown links/images do not execute scripts.

### 25. Resilience And Error States

Purpose: verify the app behaves well when the server or worker path misbehaves.

Tests:

- Server emits error event; UI shows toast.
- Server emits stale layout/task data; UI guards against crashes.
- Socket disconnects and reconnects.
- Worker process crashes.
- Scheduler fires while browser is disconnected.
- File save fails due permission error.
- Terminal process exits unexpectedly.
- Service worker port already in use.
- Browser console remains free of uncaught exceptions during smoke flows.

## Visual Regression Strategy

Start with functional screenshots on failure only. Add visual snapshots after
selectors and layout stabilize.

Candidate snapshot views:

- Tickets Kanban, dark and light.
- Ticket detail modal/panel.
- Ticket list view with filters.
- Worker grid with several worker types.
- Worker config modal for agent, shell, service, notification, marker.
- Files tab text editor and markdown preview.
- Terminal tab.
- Live Agent tab.
- Stats tab.
- Commit diff modal.

Use masking for dynamic text, timestamps, token counts, terminal prompts, and
workspace paths. Keep visual thresholds conservative and review snapshots
manually before enforcing them in CI.

## Test Data Strategy

Use deterministic fixtures:

- Temporary workspace per test or per test class.
- Local git repository fixture for Commits and clone flows.
- Local sample files for Files tab.
- Mock agent adapters for provider workers.
- Fake command scripts for shell/service workers.
- Controlled scheduler hooks for time-based workers.
- Fixed profile/team names.
- Fixed viewport and timezone.

Avoid:

- Real provider CLIs.
- Real network repositories.
- External web pages.
- Direct edits to `.bullpen/tasks` for ordinary setup.
- Shared global `~/.bullpen` state.

## Implementation Phases

### Phase 0: Foundation

Deliverables:

- `tests/playwright/` package.
- Shared server fixture.
- Shared browser fixture.
- Trace/screenshot/video artifact configuration.
- Selector helper conventions.
- First page objects for app shell, tickets, and workers.
- `pytest` markers registered.
- Documentation for running the suite locally.

Acceptance:

- One smoke test starts Bullpen, opens Chromium, verifies app shell, and exits
  cleanly.
- Test skips cleanly when Playwright or browser binaries are unavailable.
- No root-owned scaffold or `node_modules` is required in the repo.

### Phase 1: Core Smoke And Tickets

Deliverables:

- Smoke tests.
- Ticket create/edit/detail tests.
- Kanban drag/drop tests.
- List view tests.
- Theme smoke tests.

Acceptance:

- Covers the primary ticket lifecycle entirely through UI.
- Runs in Chromium in under five minutes on a developer machine.
- Captures artifacts on failure.

### Phase 2: Worker Grid And Core Execution

Deliverables:

- Worker grid creation/edit/menu tests.
- Drag ticket onto worker.
- Run queued ticket.
- Empty-run synthetic behavior tests.
- Pause/resume tests.
- Worker focus output tests.
- Basic AI worker with mock adapter.

Acceptance:

- Every visible worker menu item has at least one positive or negative test.
- Every worker action is asserted against both UI and server state.

### Phase 3: Worker Types

Deliverables:

- Shell worker suite.
- Service worker suite.
- Marker worker suite.
- Notification worker suite migrated from the current standalone test.
- Scheduling and handoff suite.

Acceptance:

- Every worker type can be created, configured, saved, reopened, triggered, and
  deleted from the browser.
- Every configuration control on each worker type round-trips.

### Phase 4: Advanced App Surfaces

Deliverables:

- Files tab suite.
- Terminal suite.
- Live Agent suite with fake backend.
- Commits and Stats suite.
- Teams and Profiles suite.
- Main-app multi-workspace suite.

Acceptance:

- High-risk surfaces have closed-loop browser coverage.
- Tests do not require real external services.

### Phase 5: Multi-Client, Auth, Resilience

Deliverables:

- Auth suite.
- Multi-client Socket.IO sync suite.
- Reconnect suite.
- Error-state and permission-failure suite.
- Accessibility keyboard smoke suite.

Acceptance:

- Browser tests catch stale UI, missing event handlers, and unusable controls.
- Browser console errors fail smoke flows unless explicitly allowed.

### Phase 6: Cross-Browser And Visual

Deliverables:

- Firefox/WebKit scheduled runs.
- Visual snapshot baseline for selected views.
- Mobile/tablet responsive subset.
- CI sharding.

Acceptance:

- Chromium is required for PR/push smoke.
- Firefox/WebKit and visual snapshots run nightly or before release.
- Flake rate is tracked and remains below an agreed threshold.

## CI Proposal

Recommended jobs:

```text
pytest-unit
  python3 -m pytest

playwright-smoke
  python3 -m pytest tests/playwright -m playwright_smoke --browser chromium

playwright-core
  python3 -m pytest tests/playwright -m "playwright_core or playwright_workers" --browser chromium

playwright-nightly
  python3 -m pytest tests/playwright --browser chromium --browser firefox --browser webkit

playwright-visual
  python3 -m pytest tests/playwright -m playwright_visual --browser chromium
```

The first PR gate should be `playwright-smoke`. Expand the required gate only
after the suite has proven stable.

## Local Developer Workflow

Install:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m playwright install chromium
```

Run smoke:

```bash
python3 -m pytest tests/playwright -m playwright_smoke
```

Run a focused file:

```bash
python3 -m pytest tests/playwright/test_workers_core.py -k run_menu
```

Run with visible browser:

```bash
PWDEBUG=1 python3 -m pytest tests/playwright/test_tickets.py -k drag
```

Open trace:

```bash
python3 -m playwright show-trace test-results/<trace>.zip
```

## Required App Instrumentation

The suite will be much less brittle if the app adds stable selectors and a few
test-only hooks.

Recommended non-user-visible additions:

- `data-pw` attributes on repeated cards, icon-only buttons, menus, modal save
  buttons, tab controls, drag handles, and route-critical controls.
- A test-only server setting to register mock agent adapters.
- A test-only scheduler clock or explicit scheduler tick endpoint enabled only
  under `BULLPEN_TEST_MODE=1`.
- A test-only fake terminal command mode or fixture shell path.
- Consistent toast container markup with severity and message attributes.
- Browser console error collection helper.

These hooks should not change production behavior and should be guarded by
test-only environment variables where they expose control surfaces.

## Flake Control

Browser suites get expensive when they are allowed to become timing-dependent.
Use these rules:

- Prefer waiting for user-visible state, server events, or persisted state over
  fixed sleeps.
- Wrap drag/drop in helper methods that assert both drag start and drop result.
- Avoid tests that rely on wall-clock scheduler timing; use controlled ticks.
- Keep each test's workspace isolated.
- Close browsers and stop Bullpen processes aggressively in teardown.
- Fail on unexpected console errors in smoke/core tests.
- Quarantine flaky tests behind a marker with an owner and removal date.
- Track runtime and flake history in CI.

## Definition Of Done For A Playwright Test

A browser test is complete when:

- It starts from isolated state.
- It performs real user actions for the behavior under test.
- It asserts visible UI outcome.
- It asserts server/socket/persisted state when practical.
- It captures trace/screenshot on failure.
- It does not require external network services.
- It cleans up server processes, workers, terminals, and temporary files.
- It has a clear marker and belongs to a documented test group.
- It avoids Bullpen Manager routes and assets.

## Risks And Mitigations

### Risk: Suite becomes too slow

Mitigation: keep PR gate small, shard feature suites, run cross-browser and
visual tests on schedule.

### Risk: Tests are brittle because selectors are unstable

Mitigation: add `data-pw` attributes and page objects before writing hundreds
of assertions.

### Risk: Worker tests require real provider CLIs

Mitigation: use mock adapters and fake executables. Real provider smoke should
remain manual or separately gated.

### Risk: Scheduler tests become time-dependent

Mitigation: add controlled scheduler hooks under test mode.

### Risk: Browser tests hide backend bugs by overusing direct state setup

Mitigation: setup may use server-backed Socket.IO helpers, but each feature
must include at least one full UI path for creation/configuration/action.

### Risk: Bullpen Manager leaks into scope

Mitigation: fail tests that navigate to `/manager` or load `static/manager/*`
unless explicitly marked in a future Manager-specific suite.

## Initial High-Value Test Backlog

1. App boots, switches tabs, reloads, and has no console errors.
2. Quick-create ticket, edit in detail panel, drag to Review.
3. Create worker, drag ticket onto it, Run, verify output and route.
4. Worker menu audit: every visible menu item has an assertion.
5. Notification worker full control round-trip and manual empty Run.
6. Shell worker `stdin-json` success and failure route.
7. Service worker start/log/stop.
8. File editor open/edit/save/reload.
9. Terminal open/type/close.
10. Two-browser sync for ticket create/edit/drag.
11. Auth login/logout and Socket.IO rejection.
12. Theme and responsive smoke for Tickets and Workers.

## Recommendation

Build the suite incrementally, starting with the fixture foundation and a small
Chromium smoke gate. Then prioritize the exact flows where Bullpen has the
highest product risk: tickets, worker menus, worker configuration, drag/drop,
run lifecycle, files, terminal, and multi-client sync.

The suite should not be a broad screenshot farm or a second backend test suite.
Its job is to prove that Bullpen's visible controls are real, complete, and
connected to live application state.
