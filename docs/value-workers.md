# Specification: Value Workers

Value workers add durable, editable data cells to the worker grid. They are
worker-shaped so they can live on the same sparse canvas as AI, Shell, Service,
Marker, and Notification workers, but they are not runnable and they do not
participate in the ticket lifecycle.

The intended mental model is "spreadsheet cells for the worker grid":

```text
Interest rate: 5.3
Target branch: release/2026-06
Retry budget: 2
```

Other workers can read those values by name or coordinate, update them through
MCP tools, and interpolate them into supported templates.

---

## Goals

- Add `type: "value"` as a first-class worker-grid card.
- Store one durable key/value pair per Value worker.
- Let the key be referenced by the card name and by its grid coordinate, for
  example `A27`.
- Support string and number values in v1.
- Preserve values across browser refreshes, server restarts, team save/load,
  export/import, copy/paste, and worker transfer.
- Expose server-backed MCP tools for reading and updating values.
- Support value interpolation in worker configuration fields, including Shell
  commands, with explicit caveats and follow-up security review requirements.
- Make Value workers visible, searchable, movable, duplicable, and deletable
  like other worker-grid cards.
- Keep Value workers independent from ticket assignment, queueing, scheduling,
  retry, subprocess, synthetic-ticket, and disposition behavior.

## Non-Goals

- No expression formulas in v1.
- No automatic recalculation graph in v1.
- No multi-cell ranges, merged cells, table regions, or full spreadsheet UI in
  v1.
- No ticket queue, ticket claiming, manual run, scheduled run, subprocess
  execution, service supervision, or notification delivery.
- No free-form JavaScript/Python expressions.
- No secret storage guarantees. Values are stored in Bullpen workspace state
  and should be treated as workspace-visible configuration, not a vault.
- No new permission boundary in v1. Any AI worker with normal Bullpen MCP
  access can read and mutate all Value workers.

---

## Worker Type Model

Reserve this worker type:

```text
type: "value"
```

Value workers occupy a real grid cell. They count as occupied for layout,
selection, minimap, keyboard navigation, Go to worker, export/import, team
save/load, transfer, copy/paste, and collision detection.

Value workers are non-runnable:

- no `Run` action,
- no `Stop` action,
- no task queue,
- no activation trigger,
- no watched column,
- no retry count,
- no disposition.

They should be closer to Marker workers in visual treatment, but closer to a
shared data store in behavior.

### Slot Fields

| Field | Type | Default | Notes |
|---|---|---:|---|
| `type` | string | `"value"` | Worker type id |
| `name` | string | `""` | Optional human label and value alias |
| `value` | string/number | `""` | Raw stored value |
| `value_type` | string | `"auto"` | `auto`, `number`, or `string` in v1 |
| `format` | object | `{ "kind": "auto" }` | Display formatting only |
| `icon` | string | `"variable"` | UI default |
| `color` | string | `"value"` | UI color token |
| `row` / `col` | positive integer | grid position | Used to derive coordinate alias |
| `updated_at` | string/null | `null` | Server timestamp for conflict/debug UI |
| `updated_by` | string/null | `null` | Optional actor label: `ui`, `mcp`, worker name |

Fields that do not apply to Value workers should be absent from newly-created
slots. Normalization should tolerate old or pasted data containing unrelated
fields, but serialization should not invent AI/Shell lifecycle fields for
Value workers.

### Coordinate Alias

Every Value worker has an implicit coordinate alias based on its current grid
location. Coordinates are the only required reference path; names are optional.

Coordinate rules:

- Bullpen should adopt a product-wide positive-coordinate policy: worker cells
  use positive integer coordinates only.
- Zero and negative coordinates are prohibited for all workers and all worker
  grid uses.
- Columns use spreadsheet letters: `A`, `B`, ..., `Z`, `AA`, `AB`, etc.
- Rows are 1-based: row `1` is the first row.
- `A1` means `{ col: 1, row: 1 }`.
- Coordinate aliases are case-insensitive: `A27` and `a27` are equivalent.
- Moving a Value worker changes its coordinate alias.
- The card name, when present, is stable across moves.

Architecture issue: the existing sparse-grid spec and parts of the current
implementation use zero-based coordinates and allow negative coordinates. The
positive-coordinate policy is broader than Value workers and should be handled
as a separate remediation phase with its own commit before or alongside the
Value worker implementation. That phase should update grid validation,
viewport origin defaults, migration rules, minimap math, keyboard navigation,
drag/drop target validation, tests, and documentation so the whole product uses
one coordinate model.

---

## Value Names And Lookup

Value worker names are optional aliases. The coordinate is the canonical
reference.

Validation rules:

- Name may be blank.
- A blank name means the value is referenced by coordinate only.
- Name uses the existing worker-name length limit unless a smaller Value-specific
  limit is introduced.
- Leading/trailing whitespace is trimmed.
- Internal whitespace is preserved.
- Names are case-insensitive for lookup.
- Duplicate names are allowed. Bullpen should not police Value worker name
  uniqueness because the rest of the product does not police worker names.

Lookup rules:

- Coordinate lookup is exact and preferred.
- Name lookup is best-effort and deterministic.
- If exactly one Value worker has a matching name, that value is used.
- If multiple Value workers have a matching name, Bullpen uses the first match
  in row-major coordinate order: lowest `row`, then lowest `col`.
- When a duplicate-name lookup resolves by row-major first match, previews,
  MCP responses, and run records should include a warning listing the matched
  coordinate and the other matching coordinates.
- Nameless values never participate in name lookup.

This makes duplicate names predictable without turning worker naming into a
validation regime. It does mean that moving a duplicate-named Value worker can
change which value a name lookup resolves to. Automations that need stability
should use coordinate references.

Limitations of optional names:

- Nameless values are harder to discover from a prompt or command line without
  looking at the grid.
- Copy/paste and duplicate can create more nameless cells, which is fine but
  makes `list_values()` more important.
- Teams that want durable semantic references should name values carefully or
  use coordinate references.

### Name Syntax In Templates

Value interpolation should "just work" for names with spaces:

```text
{interest rate}
{target branch}
```

V1 placeholder lookup should use the full text inside braces after trimming.
No quoting is required for spaces. These should all resolve to the same Value
worker:

```text
{interest rate}
{ Interest Rate }
{INTEREST RATE}
```

Coordinates are also placeholders:

```text
{A23}
{a23}
```

Lookup precedence:

1. Built-in template namespaces, such as `{ticket.title}` and `{worker.name}`,
   when a field already supports them.
2. Coordinate aliases, such as `{A23}`.
3. Value worker names, such as `{interest rate}`.

Accepted limitation: if a Value worker is named `ticket.title`, it conflicts
with the existing notification-template namespace. The precedence above avoids
breaking existing templates, but it means that Value worker cannot be
referenced with plain `{ticket.title}` syntax. Use its coordinate alias instead.
A future explicit namespace such as `{value:ticket.title}` or
`{value.ticket.title}` is deferred.

---

## Value Types

V1 supports two stored value types plus automatic inference:

| `value_type` | Meaning |
|---|---|
| `auto` | Infer number vs string from input, preserve enough raw text for display |
| `number` | Store as numeric JSON value after validation |
| `string` | Store as string exactly as entered, except for line-ending normalization |

Auto parsing rules:

- Empty input becomes an empty string.
- Integers and decimal values become numbers.
- Leading/trailing whitespace is ignored for numeric inference.
- Values with `%`, currency symbols, thousands separators, or units remain
  strings in v1 unless the user explicitly chooses a numeric format and enters
  a clean number.
- Strings that look like identifiers, dates, branches, versions, or paths stay
  strings unless they are valid plain numbers.

Examples:

| Input | Stored value | Stored type |
|---|---:|---|
| `5.3` | `5.3` | number |
| `0023` | `"0023"` | string |
| `5.3%` | `"5.3%"` | string |
| `$12.50` | `"$12.50"` | string |
| `release/2026-06` | `"release/2026-06"` | string |

Open issue: percentages and currencies are useful enough that v2 should
consider typed parsing for them, but v1 should avoid pretending formatted
strings are safe arithmetic values.

---

## Display Formats

Formatting affects display only. It must not change the stored raw value.

V1 formats:

| Format | Applies to | Notes |
|---|---|---|
| `auto` | any | Default; number values display compactly, strings left-aligned |
| `general` | any | Plain string conversion |
| `number` | number | Configurable decimal places |
| `currency` | number | Configurable decimal places and symbol; display only |
| `string-left` | string | Left-aligned |
| `string-right` | string | Right-aligned |

Suggested storage:

```json
{
  "format": {
    "kind": "number",
    "places": 2
  }
}
```

Creation and edit UI should expose format controls. MCP format updates are
deferred.

---

## UI

### Add Worker Flow

The standard Add Worker flow should include Value workers.

Recommended library entries:

- Blank value
- Number value
- Text value

The config modal should show only Value-relevant fields:

- Name
- Value
- Type: Auto, Number, String
- Format
- Color override

It should hide:

- AI provider/model/prompt/trust mode
- command/cwd/env/timeout
- service lifecycle/health fields
- notification channel config
- activation, watch column, scheduling, max retries, and disposition

### Spreadsheet Shortcut Creation

When the grid has focus and the current cell is empty, typing a printable
character starts an in-cell Value worker creation editor.

Shortcut syntax:

```text
[<label>:] <value>
```

Examples:

```text
interest rate: 5.3
target branch: release/2026-06
2
```

Behavior:

- `label: value` creates a Value worker with `name=label` and `value=value`.
- A value with no label creates a nameless Value worker referenced by
  coordinate only.
- Pressing Enter creates the Value worker directly.
- Pressing Cmd+Enter on macOS or Ctrl+Enter on Windows/Linux opens the Value
  worker creation modal with the parsed fields prefilled.
- Pressing Escape cancels without creating a worker.
- If parsing is invalid or numeric validation fails, Enter keeps the in-cell
  editor open and shows an inline error instead of creating a worker.

Parsing rules:

- Split on the first colon only.
- If the text before the first colon is empty, treat the whole input as a
  value.
- Trim the label.
- Trim the value for auto/number parsing.
- Preserve interior spaces in string values.

The direct-create path should use sensible defaults: `value_type: "auto"`,
`format: { "kind": "auto" }`, default Value color, and blank name when no
label was supplied.

### Card Rendering

Small layout:

- Header shows the name and formatted value.
- Value is right-aligned when possible.

Medium layout:

- Header shows name and formatted value.
- Body shows type/format metadata or a larger value preview.

Large layout:

- Adds direct edit controls when there is enough room.

The header display target is:

```text
interest rate                                      5.3
```

Cards must keep the active grid layout dimensions stable. Long names and long
values should truncate or wrap inside the card without changing card width or
height.

### Direct Editing

Inline direct editing is in scope for v1.

- Click value text to edit the value.
- Enter saves.
- Cmd+Enter on macOS or Ctrl+Enter on Windows/Linux opens the full config
  modal for type/format/name changes.
- Escape reverts.
- Blur saves only if the UI already uses blur-save consistently elsewhere;
  otherwise blur should not silently persist.
- Failed validation keeps the editor open and shows an inline error.
- Inline editing changes the value only. Name, type, format, and color changes
  happen in the config modal.

### Future Adjustment Controls

When the row height is larger than the minimum, show controls appropriate for
the value type:

- numeric values: stepper or slider with an automatically suggested range,
- picklist values: compact select/menu,
- strings: direct edit affordance.

These controls are deferred until after basic storage, MCP, and interpolation
are stable.

---

## Ticket Interaction

Value workers are independent of ticket flow. They should behave like
non-runnable occupied cells, not like pass-through workers.

Ticket assignment behavior:

- Dragging a ticket over a Value worker should behave like dragging over a
  blank cell: the worker card does not activate as a drop target and the
  browser shows no valid drop.
- If a client still sends an assignment/drop request for a Value worker, the
  server rejects it with a structured error and does not mutate the ticket.
- `worker:VALUE_NAME` disposition to a Value worker fails closed and sends the
  ticket to Blocked with a clear reason.
- `pass:LEFT`, `pass:RIGHT`, `pass:UP`, `pass:DOWN`, and `pass:RANDOM` should
  not select a Value worker as a destination.
- `random:PATTERN` should exclude Value workers.
- `on_queue`, manual run, and scheduled run controls are not available.

Pointer drag/drop should feel like a blank cell. Server-side routing should
fail closed because routing errors may be produced by workers or configuration
without an interactive UI affordance.

Open issue: if users want Value workers as visual waypoints later, that should
be a separate feature. Marker workers already cover pass-through waypoints.

---

## Interpolation

Value interpolation replaces placeholders in supported worker configuration
fields with the current Value worker value.

Examples:

```text
Use an interest rate of {interest rate}.
Deploy branch {target branch}.
Retry up to {retry budget} times.
```

Supported fields in v1:

- AI worker expertise prompt.
- Shell worker command.
- Shell worker working directory.
- Shell worker configured environment values.
- Service worker inline command, pre-start command, working directory, health
  command, and configured environment values.
- Notification worker toast/speech templates.

Big caveat: interpolating Value workers into shell commands is intentionally
powerful and intentionally risky. Bullpen already lets operators configure
arbitrary commands, prompts, and agent workflows that can mutate the workspace.
V1 should implement shell interpolation to explore the product value, but it
must document the expanded security exposure instead of pretending this is a
safe templating feature.

Shell interpolation implementation plan:

- Interpolate server-side immediately before preparing the shell/service run.
- Store and display both the raw configured command and the rendered command in
  the run record.
- Show a rendered command preview in the config modal for every interpolated
  Shell and Service field.
- Re-render at run time so workers see the latest values.
- Do not mutate the saved command string when values change.
- Apply the same renderer to command, cwd, env values, pre-start, and health
  command fields.
- Missing values leave placeholders unchanged and produce warnings.
- Duplicate-name matches use row-major first-match resolution and produce
  warnings.
- Rendered command warnings appear in focus output or run metadata before the
  command output.
- Shell examples and UI copy must say that Value interpolation is raw text
  substitution into commands.
- The Shell worker spec must be updated in the same implementation phase
  because it currently promises that Bullpen never interpolates command
  strings.

Do not add shell escaping in v1 unless it is designed as a separate explicit
syntax. The first implementation should be simple and inspectable: `{A1}` and
`{name}` become raw value text. Escaping rules such as shell-quoted,
JSON-quoted, URL-encoded, or path-escaped values can be added later with
explicit filters.

Potential future filter syntax:

```text
{branch|shell}
{payload|json}
{query|url}
```

V1 should not ship those filters unless the implementation is complete across
POSIX and Windows.

### Rendering Rules

- Interpolation is non-evaluating string replacement.
- Missing values leave the placeholder unchanged and add a warning to the run
  record or UI preview.
- Duplicate value names resolve to the first row-major match and warn.
- Number values are rendered using their raw canonical number, not their
  display format, unless a field explicitly asks for formatted display text.
- String values are inserted as plain text.
- Shell and service command interpolation is raw text substitution. The command
  author is responsible for quoting and escaping.

Open issue: there should be one shared server-side template renderer for
Notification templates and Value interpolation. Duplicating placeholder logic
in multiple worker implementations will create inconsistent escaping and
lookup behavior.

---

## MCP Tools

Add server-backed MCP tools for values. Tools must operate through Bullpen's
normal server state path so connected browsers receive update events.

Required v1 tools:

```text
get_value(ref)
set_value(ref, value, value_type?)
increment_value(ref, amount?)
decrement_value(ref, amount?)
list_values()
```

`ref` can be:

- a coordinate alias, such as `A23`,
- or a Value worker name, such as `interest rate`.

Tool behavior:

- `get_value` returns raw value, value type, formatted value, coordinate, name,
  updated timestamp, and updated actor.
- `set_value` validates and stores a new value.
- `increment_value` and `decrement_value` require the current value to be
  numeric and are atomic.
- `list_values` returns all Value workers in the workspace, sorted by row/col.
- Missing refs return a structured not-found error.
- Duplicate-name refs resolve to the first row-major match and return a warning
  that includes every matching coordinate.
- Attempts to write non-numeric data through increment/decrement return a
  validation error and do not mutate state.

Atomicity requirements:

- Increment/decrement must hold the same workspace/layout lock used for worker
  slot mutation.
- Two concurrent increments must not lose an update.
- MCP writes must emit the same `layout:updated` or value-specific Socket.IO
  event the UI uses.
- If layout persistence fails, the MCP call fails and the in-memory value is
  not reported as successful.

Authorization:

- Use the same MCP authentication model as existing Bullpen ticket tools.
- Shell workers currently do not receive `BULLPEN_MCP_TOKEN`; do not add token
  access just for Value workers without updating the Shell security model.
- AI workers that already have authenticated MCP access can read and mutate all
  Value workers in v1.
- No read-only or locked Value worker mode exists in v1.

---

## Persistence And Serialization

Value workers should live in the normal layout/slot storage so they move,
copy, transfer, export, import, and save with teams like other worker-grid
objects.

Requirements:

- Add `value` to the worker type registry and frontend built-in worker type set.
- Add `value` to provider/worker color validation.
- Normalize Value-specific fields in `normalize_worker_slot`.
- Preserve unknown future fields.
- Do not add runtime lifecycle fields that imply the worker can run.
- Include Value workers in export/import and team save/load.
- Copy/paste should copy the value and format.
- Duplicating or copy/pasting a named Value worker should auto-suffix the name
  the same way existing worker copy/paste does.
- Duplicating or copy/pasting a nameless Value worker keeps it nameless.
- Moving a Value worker changes coordinate lookup immediately.

---

## Events And Collaboration

When a Value worker changes, connected clients should update without refresh.

Minimum event behavior:

- Creating a Value worker emits the same layout update as creating another
  worker type.
- Updating a value emits a layout update or a smaller `value:updated` event.
- The event payload includes coordinate, name, raw value, formatted value,
  updated timestamp, and actor.
- Simultaneous edits use Bullpen's existing worker update behavior. Value
  workers do not introduce optimistic concurrency or revision checks in v1.

---

## Worker Colors UI

Add a Value entry to the worker colors UI.

Defaults:

- color key: `value`
- default: light green
- suggested hex: `#86efac` or theme-equivalent token

Value worker creation and edit modals should support the same color override
pattern as Marker and Notification workers.

---

## Accessibility

- Card name and value must be readable by screen readers.
- The card should expose its role as a non-runnable Value worker.
- Inline editing must have a visible focus state and keyboard save/cancel
  semantics.
- Color cannot be the only indication that the card is a Value worker.
- Form errors for invalid numbers and duplicate-name lookup warnings must be
  associated with the relevant input.

---

## Preliminary Architecture Decisions And Issues

### Decisions

- Store Value workers as normal worker slots in `layout.json`, not as a
  separate value-store file in v1. This keeps copy/paste, transfer,
  export/import, teams, minimap, and grid occupancy aligned with existing
  worker behavior.
- Add Value worker support through the worker type registry and normal slot
  normalization path.
- Add a small server-side value service/helper layer for lookup, parsing,
  formatting, mutation, and interpolation. Avoid scattering coordinate/name
  lookup across workers, MCP tools, and frontend event handlers.
- Make coordinate lookup canonical. Name lookup is convenience syntax.
- Use row-major first-match behavior for duplicate names everywhere: templates,
  MCP, previews, and run records.
- Run all value mutations through server-backed layout persistence and the
  same lock discipline used for worker slot mutation.
- Use one shared server-side placeholder renderer for Value interpolation and
  existing Notification templates.
- Implement Shell and Service interpolation in v1 as raw text substitution,
  with rendered previews, run-record capture, and explicit warnings.
- Treat simultaneous edits like existing worker configuration edits. Do not add
  a special concurrency model for Value workers in v1.

### Issues To Resolve During Implementation

- **Coordinate remediation**: positive-only worker coordinates affect the whole
  grid and should be implemented as a separate phase/commit. Value workers
  should not invent a private coordinate system.
- **Renderer ownership**: decide whether the shared placeholder renderer lives
  in a new `server/templates.py`, under worker utilities, or under a broader
  services layer.
- **Event granularity**: decide whether value writes emit only `layout:updated`
  or also a smaller `value:updated` event. `layout:updated` is simpler;
  `value:updated` may avoid noisy full-layout refreshes during frequent
  increments.
- **Lookup index**: v1 can scan slots for each lookup. If value counts grow,
  maintain derived indexes by coordinate and normalized name, rebuilt whenever
  layout changes.
- **Shell spec conflict**: update `docs/shell-worker.md` in the implementation
  phase because that spec currently states that Shell commands are never
  interpolated.
- **Copy suffix convention**: use the existing duplicate/copy naming convention
  exactly. The Value spec should not invent a separate suffix algorithm.
- **MCP tool contract location**: value tools should be documented alongside
  existing Bullpen MCP ticket tools and should use the same auth/connect
  diagnostics.
- **Audit trail**: v1 records `updated_at` and `updated_by`, but not a full
  history. Decide during implementation whether run records and MCP responses
  are enough for debugging value changes.

---

## Tests Required

Server:

- Value slot normalization fills defaults and preserves unknown fields.
- Value slot copy resets no runtime fields that do not apply and preserves
  value/format.
- Value workers round-trip through team save/load, export/import, transfer,
  duplicate, and restart.
- Nameless Value workers are valid and resolve by coordinate.
- Duplicate value names are valid and resolve by deterministic row-major first
  match with warnings.
- Coordinate aliases resolve after create and after move.
- `get_value`, `set_value`, `increment_value`, `decrement_value`, and
  `list_values` use server-backed state and emit updates.
- Concurrent increment/decrement calls do not lose updates.
- Ticket disposition to a Value worker fails closed with a clear Blocked
  reason.
- Random/pass routing excludes Value workers.

Frontend:

- Add Worker library includes Value.
- Value config modal hides runnable-worker fields.
- In-cell shortcut editor parses `label: value`, value-only, and colon inside
  the value.
- Card renders name/value in Small, Medium, and Large layouts without changing
  card dimensions.
- Worker colors UI includes `value`.
- Duplicate-name warnings and invalid-number errors are visible.

Template/interpolation:

- `{A23}` and `{interest rate}` resolve.
- Names with spaces resolve.
- Missing values warn and do not silently erase placeholders.
- Duplicate-name values resolve by row-major first match and warn.
- Built-in template namespace precedence remains compatible with Notification
  templates.
- Shell command, cwd, env, service command, pre-start, and health command
  strings interpolate values and record rendered previews/warnings.

Architecture:

- Product-wide positive-coordinate validation rejects zero and negative worker
  coordinates after the coordinate remediation phase.
- Coordinate aliases use `A1` for `{ col: 1, row: 1 }`.

---

## Deferred Features

### Read-Only And Locked Values

V1 has no read-only or locked Value workers. Any AI worker with normal Bullpen
MCP access can mutate all values, and any editor can change values through the
UI.

Future controls should define:

- `locked`: UI cannot edit the value without first unlocking it.
- `read_only`: workers and MCP tools cannot mutate the value.
- MCP write allowlists by worker, worker type, or trust mode.
- UI affordances for locked/read-only state on the card and in the config
  modal.
- Behavior for increment/decrement on read-only values.
- Export/import and team save/load semantics for locks.
- Whether locked/read-only flags are advisory local workflow controls or real
  authorization checks.

### Security Review For Value Interpolation

Shell and Service interpolation deliberately increases Bullpen's already-large
automation surface. It should ship in v1 with clear warnings, but it needs a
follow-up security review focused on Value-specific risks.

Review areas:

- Raw Value text substituted into `/bin/sh -c` or `cmd.exe /c` command strings.
- Values changed by AI workers immediately affecting later Shell/Service runs.
- Prompt-to-value-to-shell escalation paths.
- Duplicate-name confusion causing a command to receive a different value than
  the operator expected.
- Coordinate moves changing which value a command receives.
- Missing placeholders remaining in commands and being interpreted by the
  shell or downstream tools.
- Values embedded into env vars, working directories, health checks, and
  pre-start commands.
- Rendered command exposure in logs, run records, browser payloads, export
  archives, team saves, and transfers.
- Secret-like values stored in layout state and interpolated into plaintext
  command records.
- Cross-platform quoting differences between POSIX shells and Windows command
  execution.

Follow-up design questions:

- Should Value interpolation support explicit escaping filters such as
  `|shell`, `|json`, `|url`, or `|path`?
- Should Shell/Service config have a per-worker toggle for interpolation, or is
  interpolation always on when placeholders are present?
- Should commands fail closed when a placeholder is missing, or is
  placeholder-preserving warning behavior sufficient?
- Should high-risk interpolated commands show an additional confirmation or
  warning in the config modal?
- Should AI workers be able to mutate values used by Shell/Service workers
  without a separate trust mode?

### Stable Worker IDs

Stable worker IDs are not part of the v1 Value worker design. The mainline spec
uses coordinates and names because those match the current worker-grid model.

A future stable ID architecture would help in several places:

- Preserve references across worker moves and renames.
- Let MCP tools address a worker without relying on coordinate or duplicate
  name resolution.
- Make audit records robust when a Value worker moves after a write.
- Let interpolation use an explicit durable reference if the UI exposes one.
- Improve worker transfer and import/export conflict handling.
- Support future formula dependency graphs without invalidating references on
  move.
- Support stronger concurrency checks and update histories.
- Make cross-workspace copy/move provenance easier to trace.
- Give browser events a durable target independent of slot index and
  coordinate.

Open questions for that future architecture:

- Are IDs assigned to all worker types or only Value workers?
- Are IDs persisted forever, or regenerated on duplicate/copy/paste?
- How are IDs handled during team save/load, export/import, and transfer?
- Are IDs user-visible, copyable, or purely internal?
- How are collisions repaired during import?
- Do IDs become part of the public MCP and template syntax?

### Expressions

Later phases can add formula values.

Candidate syntax:

```text
=A1 * 1.05
=value("interest rate") / 100
```

Requirements before implementation:

- Define the function suite.
- Define name lookup for spaces and special characters.
- Keep formulas non-Turing-complete.
- Detect cycles.
- Report formula errors without corrupting the previous valid value.
- Decide whether formulas store both expression text and last computed value.

### Recalculation

When formulas exist, a value change should update dependent values.

V1 formula proof of concept can use brute-force recomputation if the graph is
small. A scalable version should maintain dependencies and recalculate only
affected cells.

Required failure modes:

- cycle detected,
- missing dependency,
- ambiguous dependency,
- invalid type for operation,
- divide by zero.

### Extended Value Types

Potential future types:

- percentage,
- currency,
- boolean,
- date,
- duration,
- picklist,
- JSON object,
- secret reference.

Picklist needs a better product name before shipping.

### Value Defaults And Environment Sets

Future workflow features may include:

- "reset to default" values,
- per-environment value sets,
- per-branch value sets,
- value import/export as a separate operator action,
- value snapshots before a worker run.
