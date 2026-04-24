# Stats Tab Proposal

**Created:** 2026-04-24

## Goal

Add a project-level **Stats** tab to Bullpen that helps a user understand the current workspace at a glance: live ticket load, archive flow, token cost, and recent trend. The tab should fit between **Files** and **Live Agent** in the main tab strip.

The first version should be useful without adding a database or analytics subsystem. It can derive almost everything from the existing live and archived ticket objects already available through the Socket.IO task list paths.

## Tab Placement

Current tab order:

1. Tickets
2. Workers
3. Files
4. Commits
5. Live Agent tabs
6. Worker focus tabs

Recommended order:

1. Tickets
2. Workers
3. Files
4. Stats
5. Commits
6. Live Agent tabs
7. Worker focus tabs

This puts Stats near Files because both are project inspection surfaces. It also keeps Live Agent tabs grouped after the fixed project tabs.

Use the Lucide `chart-no-axes-column` icon if available, falling back to `bar-chart-3` or `activity`.

## Product Shape

The Stats tab should be a compact multi-pane dashboard rather than a report page. It should feel like an operations view: dense, scannable, and calm.

### Top Summary Strip

Four small metric tiles:

- **Open tickets:** count of live, non-archived tickets.
- **Archived tickets:** count of archived tickets loaded for the active workspace.
- **Done waiting:** count of live tickets with `status === "done"`.
- **Token total:** sum of `task.tokens` across live and archived tickets.

Each tile should show a primary number, a short label, and a tiny secondary hint such as "live", "archive", or "all time".

### Text Status Pane

A left-side status pane should answer "what is open right now?"

Sections:

- **Open by status:** one row per configured column, using the existing column label/color.
- **Open by type:** counts for `task`, `bug`, `feature`, `chore`, plus any custom types present in tickets.
- **Open by priority:** urgent, high, normal, low.
- **Archive:** archived total and archived token total.

Rows should use counts and short horizontal bars. This keeps the text pane readable without turning it into a table-heavy page.

### Trend Pane

Three small sparkline panels:

- **Daily archived tickets:** count of archived tickets by archive day.
- **Daily open tickets:** count of currently open tickets by creation day.
- **Daily archived ticket tokens:** sum of archived ticket tokens by archive day.

Recommended default window: last 14 days, including today.

Important caveat: archived tickets currently appear to preserve ticket metadata, but may not have a first-class `archived_at` field. If no archive timestamp exists, use the best available fallback in this order:

1. `archived_at`
2. `updated_at`
3. `created_at`

The UI should label this as "by recorded date" until `archived_at` is guaranteed.

### Activity Pane

Add one medium pane for "recent movement" to make the dashboard less sterile:

- Recently archived tickets, newest first.
- Show title, type, tokens, and date.
- Limit to 5-8 items.
- Clicking a row opens the ticket detail panel in read-only mode, matching the archived ticket behavior in list view.

This pane is useful even when the sparklines are flat.

### Optional Small Panes

Good second-pass additions:

- **Worker queue load:** count of queued ticket IDs across active worker slots.
- **Assigned tickets by worker:** current ticket queue counts by worker name.
- **Oldest open tickets:** top 5 live tickets by `created_at`.
- **Token hotspots:** top 5 tickets by `tokens`.

Avoid adding too many panes in v1. The strongest first version is: summary strip, status pane, trend pane, recent archive pane.

## Data Sources

Use existing frontend state first:

- Live tickets: `state.tasks`
- Columns: `state.config.columns`
- Workers/layout: `state.layout`
- Archived tickets: `workspaces[activeWorkspaceId].archivedTasks`

Archived tickets are already fetched through:

```javascript
socket.emit('task:list', _wsData({ scope: 'archived' }));
```

When the Stats tab is selected, `setActiveTab('stats')` should request archived tickets for the active workspace. That keeps the dashboard accurate without changing server storage.

## Frontend Implementation

Add a new no-build Vue component:

- `static/components/StatsTab.js`

Props:

- `tasks`
- `archivedTasks`
- `columns`
- `layout`
- `workspaceId`

Emits:

- `select-task`

Component responsibilities:

- Compute grouped counts locally.
- Render sparklines as inline SVG or small div-based bars.
- Keep the component passive: no socket calls inside the component unless the app already uses that pattern elsewhere.
- Use existing helpers where available for icon rendering and number formatting.

`static/index.html` should include the new script before `app.js`.

`static/app.js` changes:

- Register `StatsTab`.
- Add `{ id: 'stats', label: 'Stats', icon: 'chart-no-axes-column' }` after Files in `allTabs`.
- Add `stats: 'chart-no-axes-column'` to `tabIcon`.
- Update `setActiveTab(tabId)` to request archived tasks when `tabId === 'stats'`.
- Render `<StatsTab v-if="activeTab === 'stats'" ... />`.

Suggested render binding:

```html
<StatsTab
  v-if="activeTab === 'stats'"
  :tasks="state.tasks"
  :archived-tasks="workspaces[activeWorkspaceId]?.archivedTasks || []"
  :columns="state.config.columns"
  :layout="state.layout"
  :workspace-id="activeWorkspaceId"
  @select-task="selectTask"
/>
```

## Styling

Add styles in `static/style.css` using the existing dashboard/card language where possible.

Recommended structure:

- `.stats-tab`
- `.stats-summary-grid`
- `.stats-metric`
- `.stats-dashboard-grid`
- `.stats-pane`
- `.stats-pane-header`
- `.stats-row`
- `.stats-row-bar`
- `.stats-sparkline`
- `.stats-recent-list`

Layout:

- Desktop: summary strip on top, then a two-column grid.
- Mobile/narrow: one column.
- Avoid nested cards. Panes should be direct dashboard blocks.

Visual tone:

- Use existing CSS variables.
- Use ticket column colors for status bars.
- Keep sparklines restrained and readable, with labels outside the chart.

## Server Considerations

V1 does not need a new server endpoint.

However, a better future version should add or guarantee:

- `archived_at` when a ticket is archived.
- `updated_at` on task updates if not already consistently present.
- Optional server-computed stats endpoint if archived ticket volume becomes large.

If adding `archived_at`, do it through the existing server-backed archive functions in `server/tasks.py` and socket events in `server/events.py`. Do not write `.bullpen/tasks` files directly from the frontend or scripts.

## Edge Cases

- No archived tickets: show zero metrics and empty sparkline states.
- No dates on older tickets: group them under "Undated" in text panes, and omit them from daily sparklines.
- Custom columns: include them automatically in "Open by status".
- Custom ticket types: include them after built-in types.
- Missing token counts: treat as zero, display as `-` for individual ticket rows.
- Workspace switch: Stats should recompute immediately from the active workspace and refresh archived tickets.

## Test Plan

Recommended tests:

- Frontend regression test that `Stats` appears after `Files` and before `Commits`/Live Agent tabs.
- Frontend text test that `StatsTab.js` accepts live and archived ticket props and emits `select-task`.
- Unit-style test for grouping logic if helper functions are extracted.
- Socket/event test is not required for v1 if reusing existing `task:list`.

Manual checks:

- Open Stats with no archived tickets.
- Archive a done ticket, open Stats, verify archived count changes.
- Switch workspaces and verify counts update.
- Verify mobile width does not overlap or truncate metric labels.

## Implementation Tranches

### T1: Static Dashboard From Existing State

- Add `StatsTab.js`.
- Register and render the tab.
- Compute live counts, archived counts, token total, grouped status/type/priority counts.
- Add responsive CSS.

### T2: Archive-Aware Trends

- Request archived tasks when Stats is selected.
- Add 14-day daily sparklines for archived count, open created count, and archived tokens.
- Add recent archive pane with read-only ticket clickthrough.

### T3: Timestamp Polish

- Add `archived_at` to archived tickets.
- Backfill only opportunistically or leave older archived tickets on fallback dates.
- Update sparkline labels from "recorded date" to "archive date" once reliable.

### T4: Worker/Cost Extras

- Add worker queue load, assigned-by-worker, oldest open tickets, and token hotspots if the v1 dashboard feels too sparse after real use.
