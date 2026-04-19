# Command Palette

## Goal

Bullpen needs a visible command surface that behaves more like the VS Code command palette than the
current quick-create box. The default action should remain fast ticket creation: typing plain text
and pressing Enter creates a ticket. Everything else should be discoverable through an explicit
command mode with ranked suggestions, descriptions, shortcuts, and safe confirmation for destructive
actions.

The palette is also the long-term action registry for Bullpen. Menus, keyboard shortcuts, toolbar
buttons, and future automations should be able to call the same command definitions instead of
duplicating action wiring across components.

## Previous Implementation

Before this work, the toolbar input was implemented in `TopToolbar.submitQuickCreate()` and delegated
slash commands to `runCommandBar()` in `static/app.js`.

Problems:

- Discovery is essentially absent. `/help` emits a toast with a short command list, but the user
  must already know that `/help` exists.
- Command behavior is a hard-coded `if` chain in `runCommandBar()`, so adding commands increases
  parser complexity and hides the available command surface.
- Plain quick-create parsing exists in both `TopToolbar.submitQuickCreate()` and
  `_splitQuickCreateText()`.
- Commands have no metadata: no labels, descriptions, icons, aliases, categories, parameter
  schemas, availability rules, or destructive-action flags.
- There is no command result preview. Users cannot see whether Enter will create a ticket, switch a
  tab, archive tasks, start a worker, or fail validation.
- The leading slash command mode is functional but not very VS Code-like. Slash also has an existing
  secondary meaning as the title/description separator for quick ticket creation.
- Context actions such as worker start/stop, selected ticket operations, file commands, commit
  commands, and project switching are only exposed through local UI controls.

## Interaction Model

The toolbar center becomes a palette combobox, not a bare input. It remains always visible.

Default mode:

- Typing plain text creates a ticket.
- The top suggestion is always `Create ticket: "<typed title>"`.
- If the text contains the ticket body separator, parse it as title and description. Keep the
  existing `Title / description` shorthand as the product syntax.
- Empty input shows high-value commands and recent commands rather than a blank box.

Command mode:

- `>` is the primary command-mode prefix, matching VS Code's command palette.
- `/` is not a command prefix. It remains the quick-create title/body separator.
- Command mode searches command labels, aliases, categories, and keywords.
- The placeholder should teach the grammar: `New ticket / description, or > commands`.

Entity modes:

- `@` searches addressable entities: workers, projects, profiles, agents, and chat sessions. It is
  primarily used as an argument picker inside commands but may also be entered directly.
- `#` searches tickets by title, id, tags, and status.
- `:` searches columns/statuses.
- These entity prefixes should not replace command mode; they make command arguments discoverable.

Keyboard:

- `Cmd/Ctrl+K` opens the full overlay palette and focuses the input.
- `Esc` closes the overlay or clears the current prefix mode.
- `Up/Down` changes the highlighted suggestion.
- `Enter` runs the highlighted suggestion.
- `Cmd/Ctrl+Enter` creates the default ticket immediately from default mode.
- `?` inside an empty palette shows command help/categories.

Surface:

- The toolbar combobox should show suggestions in place for quick use.
- `Cmd/Ctrl+K` should open a larger centered overlay with the same input and result model.
- Both surfaces use the same command registry and execution path.

## Prefix Grammar

Plain text:

```text
Fix stale worker state / Reconcile task queue when ticket is dragged out of In Process.
```

Creates a ticket with title `Fix stale worker state` and body
`Reconcile task queue when ticket is dragged out of In Process.`

Command mode:

```text
>tab workers
```

Switches to the Workers tab. Commands are first-class palette commands, not a legacy parser.

Entity arguments:

```text
>assign #stale-task @Reviewer
>project @bullpen
>move #abc123 :Review
```

The MVP does not need full natural-language argument parsing. It only needs an architecture that can
grow into this model. Initial commands may open a secondary picker step for missing arguments.

## Architecture

Add a command registry module, for example `static/commands.js`.

Each command is a plain object:

```js
{
  id: 'ticket.create',
  title: 'Create Ticket',
  subtitle: 'Create a new ticket in the active project',
  group: 'Tickets',
  icon: 'tag',
  prefixes: ['>'],
  aliases: ['new ticket', 'new', 'ticket', 'create'],
  keywords: ['issue', 'task', 'todo'],
  shortcut: 'Enter',
  available(ctx) { return !!ctx.activeWorkspaceId; },
  parameters: [
    { name: 'title', type: 'text', required: true },
    { name: 'description', type: 'text', required: false },
  ],
  run(ctx, args) { ctx.actions.quickCreateTask(args); },
}
```

Command registry responsibilities:

- Own command metadata.
- Own command availability and disabled reasons.
- Own parameter definitions and picker strategy.
- Own command execution dispatch.
- Provide a stable command id namespace.
- Avoid direct DOM access. UI components should pass a context object and action adapters.

Palette component responsibilities:

- Render the input and suggestions.
- Detect prefix mode.
- Perform lightweight fuzzy filtering.
- Show command groups, descriptions, shortcuts, and disabled states.
- Manage keyboard navigation and selected result.
- Request confirmation before running destructive commands.
- Emit command execution events or call a supplied `runCommand(commandId, args)` adapter.

Application context:

`static/app.js` should build a `paletteContext` object from current app state:

```js
{
  activeWorkspaceId,
  activeTab,
  selectedTask,
  selectedWorkerSlot,
  tasks,
  columns,
  workers,
  projects,
  profiles,
  chatTabs,
  themes,
  ambientPresets,
  actions: {
    quickCreateTask,
    createTask,
    updateTask,
    deleteTask,
    archiveTask,
    archiveDone,
    selectTask,
    moveTask,
    setActiveTab,
    setTicketListScope,
    addLiveAgentTab,
    closeLiveAgentTab,
    openFocusTab,
    closeFocusTab,
    startWorkerSlot,
    stopWorkerSlot,
    duplicateWorker,
    removeWorker,
    saveWorkerConfig,
    assignTask,
    showCreateModal,
    showColumnManager,
    exportWorkspace,
    exportWorkers,
    exportAll,
    importWorkspace,
    importWorkers,
    importAll,
    switchWorkspace,
    addProject,
    newProject,
    cloneProject,
    removeProject,
    toggleLeftPane,
    setTheme,
    setAmbientPreset,
    setAmbientVolume,
  },
}
```

This makes commands testable without mounting the full app. Commands can be unit-tested by passing a
fake context and asserting that the expected action adapter was called.

## Ranking And Display

Result ranking should be simple and predictable:

1. Exact command alias match.
2. Prefix match on title or alias.
3. Fuzzy match on title, alias, keywords, group.
4. Recently used command boost.
5. Contextual boost for active tab and selected entities.

Rows should show:

- Icon.
- Primary label.
- Secondary description or target.
- Category badge.
- Shortcut or prefix hint.
- Disabled reason when unavailable.

Default-mode examples:

- `Create ticket: "Fix worker pass links"`
- `Create ticket with description`
- `Search tickets for "worker pass"`
- `Open command mode`

Command-mode examples:

- `Open Tickets`
- `Open Workers`
- `Move Selected Ticket to Review`
- `Start Selected Worker`
- `Archive Done Tickets`

## Toolbar Help

The toolbar field must teach its two jobs without requiring documentation:

- Empty placeholder: `New ticket / description, or > commands`.
- Empty suggestions include `Create ticket`, `Show commands`, and `How to add a description`.
- When the user types plain text, the first result previews exactly what Enter will create.
- If the text contains `/`, the result preview must split title and description visibly:
  `Create ticket: "Title" with description`.
- The title/body separator remains `/`. Do not replace it with `--` or another syntax.
- Command mode only starts when `>` is the first non-whitespace character.

## Command Surface

The first implementation should expose commands that already have reliable app actions. Commands
that require new argument pickers can land disabled or as follow-up work.

### Tickets

| Command | Notes |
|---|---|
| Create Ticket | Default Enter action in plain-text mode; command-mode version opens modal or uses typed args. |
| Create Bug / Task / Chore / Feature | Pre-fill ticket type when creating. |
| Open Selected Ticket | Opens the current selected ticket. |
| Search Tickets | Switches to Tickets list view and seeds search once list search is externally controllable. |
| Show Live Tickets | Switches Tickets list scope to live. |
| Show Archived Tickets | Switches Tickets list scope to archived and requests archived list. |
| Move Selected Ticket to Inbox/Backlog/Review/Done/Blocked/custom column | Requires selected ticket; disallow direct move into worker-owned columns unless routed through assignment. |
| Archive Selected Ticket | Requires selected ticket. |
| Archive Done Tickets | Existing bulk archive flow with confirmation. |
| Delete Selected Ticket | Destructive; confirmation required. |
| Clear Selected Ticket Output | Destructive-ish; confirmation recommended. |
| Copy Selected Ticket ID | Uses clipboard when available. |

### Views And Navigation

| Command | Notes |
|---|---|
| Open Tickets | Existing `setActiveTab('tasks')`. |
| Open Workers | Existing `setActiveTab('workers')`. |
| Open Files | Existing `setActiveTab('files')`. |
| Open Commits | Existing `setActiveTab('commits')`. |
| Open Live Agent Chat | Existing chat tab selection/creation. |
| Add Live Agent Tab | Existing `addLiveAgentTab`. |
| Close Current Live Agent Tab | Available only on closable chat tabs. |
| Toggle Left Pane | Existing action. |
| Tickets: Kanban View | Existing `ticketsViewMode = 'kanban'`. |
| Tickets: List View | Existing `ticketsViewMode = 'list'`. |
| Workers: Home | Calls worker grid `jumpHome`; requires exposing the command through BullpenTab or app-level action. |
| Workers: Fit / Show Workers | Calls worker grid `fitOccupied`; label should explain current behavior. |
| Workers: Go To Cell | Existing grid command UI exists inside BullpenTab; expose as command when active. |

### Workers

| Command | Notes |
|---|---|
| Add Worker | Opens worker library for selected/hovered cell or asks for profile/location. |
| Configure Selected Worker | Opens WorkerConfigModal. |
| Start Selected Worker | Existing `startWorkerSlot`; disabled unless selected worker can start. |
| Stop Selected Worker | Existing `stopWorkerSlot`; disabled unless worker is working. |
| Watch Selected Worker | Opens focus tab. |
| Pause / Unpause Selected Worker | Existing save config with `paused`. |
| Duplicate Selected Worker | Existing `duplicateWorker`. |
| Copy Selected Worker | Calls BullpenTab copy helper; requires exposing selected worker command action. |
| Delete Selected Worker | Existing `removeWorker`; destructive confirmation already exists. |
| Copy Worker To Project | Existing transfer modal with mode `copy`. |
| Move Worker To Project | Existing transfer modal with mode `move`; destructive-ish confirmation recommended. |
| Assign Selected Ticket To Selected Worker | Existing `assignTask`; requires both selected ticket and selected worker. |
| Repair Pass Links | Follow-up command for the pass-link policy ticket; can start disabled until implemented. |

### Projects And Workspaces

| Command | Notes |
|---|---|
| Switch Project | Uses `@project` picker and `switchWorkspace`. |
| Add Existing Project | Existing `project:add`; currently prompts in left pane. |
| New Project | Existing `project:new`; needs path argument/picker. |
| Clone Project | Existing `project:clone`; needs URL and optional path. |
| Remove Project | Existing `project:remove`; destructive confirmation. |
| Export Project | Existing export workspace. |
| Export Workers | Existing export workers. |
| Export All | Existing export all. |
| Import Project | Existing import workspace; file picker command. |
| Import Workers | Existing import workers; file picker command. |
| Import All | Existing import all; file picker command. |

### Files

| Command | Notes |
|---|---|
| Open File | Uses `@` or file picker result; requires exposing file tree search/index. |
| Save Current File | Available when FilesTab editor has unsaved edits; requires exposing editor state. |
| Close Current File | Available when FilesTab has an active file. |
| Reload Current File | Available in FilesTab. |

### Future File Search

File search is deferred to a later phase. It should not block the palette MVP.

When implemented, file search needs a real index or server-backed query rather than walking the
visible tree in the palette component. The command should be added as `Search Files`, support
workspace scoping, and return file path results that can open in `FilesTab`.

### Commits

| Command | Notes |
|---|---|
| Open Commit By Hash | Existing `openCommitDiffFromTicket(hash)` path can be generalized. |
| Refresh Commits | Existing CommitsTab action; requires app-level command hook or tab event. |
| Show Latest Commits | Switches to Commits tab. |

### Chat

| Command | Notes |
|---|---|
| Open Live Agent Chat | Existing behavior. |
| New Live Agent Chat | Existing add tab. |
| Stop Current Chat Response | Existing `chat:stop`; available only in active chat tab with active stream. |
| Clear Current Chat | Existing `chat:clear`; confirmation recommended. |

### Columns

| Command | Notes |
|---|---|
| Manage Columns | Existing ColumnManager modal. |
| Move Selected Ticket To Column | Uses `:` column picker. |
| Show Column | Future filter command. |

### Preferences

| Command | Notes |
|---|---|
| Change Theme | Existing `setTheme`; uses theme picker. |
| Set Ambient Sound | Existing `setAmbientPreset`; uses ambient picker. |
| Set Ambient Volume | Existing `setAmbientVolume`; numeric argument. |
| Toggle Event Sounds | Existing EventSounds flag. |
| Toggle Event Sound: Task Start/Done/Error/etc. | Existing EventSounds per-event flags. |

### Help And Meta

| Command | Notes |
|---|---|
| Show Commands | Opens command-mode suggestions. |
| Show Keyboard Shortcuts | New help panel or modal. |
| Open Bullpen on GitHub | Existing toolbar menu action. |
| Copy Workspace Path | Clipboard command. |
| Copy Project ID | Clipboard command. |

## Safety Rules

- Destructive commands must show confirmation unless already confirmed by the underlying action.
- Commands that mutate running workers or in-progress tickets must preserve existing confirmations.
- Commands unavailable in the current context should still be discoverable, but disabled with a
  short reason: `Select a worker first`, `Open a project first`, `No done tickets to archive`.
- Do not run shell commands from the palette. The palette triggers Bullpen application actions only.
- Import commands must use a browser file picker; typed paths should not silently read local files.

## Implementation Plan

1. Add `static/commands.js` with a small command registry and fuzzy filtering helper.
2. Add command palette UI that can render as toolbar dropdown and modal overlay.
3. Replace the bare `TopToolbar.quickCreateText` input with the palette surface in compact toolbar
   mode.
4. Wire `Cmd/Ctrl+K` in the palette surface to open overlay mode.
5. Replace `runCommandBar()` with registry-backed execution. Remove the hard-coded slash parser
   without preserving the old parser as a parallel path.
6. Implement `>` commands as first-class registry commands.
7. Add the initial command set: ticket create, tab navigation, ticket view/scope, left pane, theme,
   ambient, volume, export/import, live chat open/add, column manager, archive done.
8. Add context-aware selected-ticket and selected-worker commands after selected worker state is
   cleanly exposed from `BullpenTab` to `app.js`.
9. Add entity pickers: tickets (`#`), workers/projects/profiles (`@`), columns (`:`).
10. Add tests for registry filtering, prefix parsing, disabled states, command execution dispatch,
    and registry-backed `>` commands.

## MVP Acceptance Criteria

- The toolbar field visibly suggests `Create ticket` and command-mode hints before the user knows
  any command syntax.
- The toolbar field visibly teaches `Title / description` and previews the title/body split before
  creation.
- `Cmd/Ctrl+K` opens an overlay palette.
- Plain text + Enter still creates a ticket.
- `>` displays searchable commands.
- The old `runCommandBar()` hard-coded parser is removed. Commands execute through the
  command registry only.
- Command results show labels and descriptions before execution.
- At least 25 commands are discoverable from the palette in the first pass.
- Disabled commands are visible with reasons.
- Destructive commands require confirmation.
- The command registry is declarative enough that adding a new command does not require editing a
  central parser switch/if chain.

## State Ownership Decision

Selected ticket state already lives in `app.js`; selected worker state should follow the same model.

Recommended approach:

- `app.js` owns `selectedWorkerSlot` and `selectedWorkerCoord`.
- `BullpenTab` receives those values as props and emits `select-worker` when grid selection changes.
- Palette commands read selected-worker context from `app.js`.
- Worker-grid-only commands such as Home, Fit, Go To Cell, Copy Worker, and Paste Worker should be
  exposed through a small BullpenTab command adapter registered with `app.js`, because those commands
  depend on viewport-local methods and clipboard state that should not be hoisted wholesale.

This gives the palette enough global context for selected-worker actions without moving all sparse
grid interaction state into the root app.

## Closed Decisions

- `>` is the visible command prefix for the MVP.
- `Title / description` remains the quick-create title/body syntax.
- The legacy hard-coded command parser must be removed outright.
- File search is deferred to a future phase.
