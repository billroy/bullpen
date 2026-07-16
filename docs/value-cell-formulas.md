# Value Cell Formulas

## Status

Functional proposal for adding spreadsheet-style formulas to Bullpen Value
workers. This proposal builds on the storage, formatting, history, MCP, and
value-change trigger contracts in:

- `value-workers.md`
- `value-cell-formatting.md`
- `value-change-trigger.md`
- `conditional-value-triggers.md`

Formula support is a later phase of Value workers. It does not change ordinary
constant Value cells or make Value workers runnable.

The original P0 decisions in this proposal were accepted on 2026-07-15. The P0
revision to structural relocation semantics was accepted on 2026-07-16.
Remaining P1 and P2 items are explicitly open unless another section records a
decision.

---

## Summary

A formula cell is a normal Value worker whose stored input begins with `=`.
Bullpen stores the formula source separately from its last successful computed
value, evaluates it on the server, and displays the computed value using the
existing Value type and formatting system.

Example:

```text
=A4 * (1 + tax_rate)
=SUM(B2:B12)
=IF(counter > 10, "high", "normal")
```

Formula evaluation is deterministic, server-authoritative, sandboxed, and
non-Turing-complete. Formulas may use literals, operators, Value-cell
references, rectangular coordinate ranges, and a fixed allowlist of functions.
They may not run code, access files or the network, mutate other cells, or call
Bullpen tools.

When a constant Value changes, Bullpen recalculates every affected formula in
dependency order. The first implementation may discover affected formulas by
scanning all formula cells, but it must still build a dependency graph for the
current recalculation pass so it can order evaluation and detect cycles.

---

## Goals

- Let users enter formulas in Value cells with familiar spreadsheet syntax.
- Reference Value cells by coordinate or stable human-readable name.
- Support relative, absolute, and mixed coordinate references consistently for
  copy, paste, duplicate, drag, move, and group relocation.
- Recalculate dependent formulas after every accepted server-backed value
  write or formula edit.
- Preserve the last successful computed value when a formula cannot evaluate.
- Make successful computed values participate in display formatting, history,
  interpolation, MCP reads, and value-change triggers like constant values.
- Detect cycles, missing references, type errors, and invalid formulas without
  corrupting other Value state.
- Keep evaluation behavior identical across UI, MCP, import, and collaboration.
- Provide enough common functions for workflow math, budgeting, text assembly,
  engineering conversion, and date calculations.
- Leave a clean path from whole-workspace scanning to indexed dependency
  tracking without changing persisted formula syntax.

## Non-Goals

- Full Excel, Google Sheets, or OpenFormula compatibility.
- Arbitrary JavaScript, Python, shell, SQL, regular-expression execution, or
  user-defined functions.
- Macros, lambdas, recursion, iteration, goal seek, solver, or circular
  calculation modes.
- Cross-workspace, cross-file, ticket-field, worker-field, or external-data
  references.
- Named ranges, whole-row or whole-column ranges, unions, intersections,
  spilled arrays, array literals, or dynamic arrays in the first release.
- Formula-driven mutation of another cell.
- Locale-specific formula grammar. Formula source always uses `.` for decimal
  and `,` for argument separation.
- Exact Excel floating-point quirks, date serial numbers, function coverage,
  error coercion, or implicit intersection.
- High-frequency real-time calculation. Value workers remain durable workflow
  state, not a telemetry engine.

---

## Terminology

- **Constant cell**: a Value worker with no formula.
- **Formula cell**: a Value worker with non-empty `formula.source`.
- **Formula source**: the user-authored string, including the leading `=`.
- **Computed value**: the most recent successful result of evaluating a
  formula.
- **Dependency**: a Value cell read directly by a formula, including each Value
  cell currently covered by a coordinate range.
- **Dependent**: a formula cell that directly or transitively reads another
  Value cell.
- **Dirty**: needing evaluation because the formula changed, a dependency
  changed, its coordinate-sensitive context changed, or it is volatile.
- **Volatile function**: a function whose result can change without a Value
  write, such as `NOW()` or `TODAY()`.
- **Calculation generation**: one server-controlled cascade beginning with one
  or more root mutations and ending when affected formulas have succeeded or
  entered an error state.

---

## Persisted Model

Formula cells remain `type: "value"`. Do not add a separate worker type.

Suggested fields:

```json
{
  "type": "value",
  "name": "Total",
  "value": 124.5,
  "value_type": "auto",
  "resolved_value_type": "number",
  "formula": {
    "source": "=SUBTOTAL + TAX",
    "version": 1
  },
  "formula_state": {
    "status": "ok",
    "error_code": null,
    "error_message": null,
    "calculated_at": "2026-07-15T14:22:31Z"
  },
  "updated_at": "2026-07-15T14:22:31Z"
}
```

Rules:

- `formula` is absent or `null` for a constant cell.
- `formula.source` preserves the normalized source, including `=`. Normalize
  line endings and trim only leading/trailing whitespace outside the formula;
  preserve whitespace inside string literals.
- `formula.version` identifies the grammar/evaluator contract. Version `1` is
  defined by this document.
- `value` is the last successful computed result. It is never overwritten with
  an error token or partially calculated value.
- `resolved_value_type` describes `value`, not the formula source.
- `value_type` remains the declared result policy. `auto` accepts supported
  result types; `number` rejects a non-numeric result; `string` converts a
  successful scalar result to canonical text.
- `formula_state.status` is `ok`, `error`, `pending`, or `stale`.
- Error details are persisted so refreshes and other clients show the same
  state. Internal stack traces are not persisted or sent to clients.
- A parsed AST and dependency index are derived data. They should not be
  persisted in the initial implementation.
- Existing constant cells require no migration. Importing a legacy Value cell
  whose string value begins with `=` does **not** silently convert it; formula
  interpretation occurs only through a formula-aware live entry or an import
  format that explicitly declares `formula`.

### Result Types

The evaluator supports scalar number, string, Boolean, and date/time values,
plus internal range values used only as function arguments.

- Numbers are finite IEEE-754 doubles. `NaN` and infinities are errors.
- Strings are Unicode strings.
- Booleans are evaluator values. Until Value cells gain a Boolean display
  type, a top-level Boolean result is stored as the lowercase string `true` or
  `false` under `auto`, and is rejected by declared type `number`.
- Date-only results are stored as ISO `YYYY-MM-DD` strings.
- Date-time results are stored as UTC ISO-8601 strings ending in `Z`.
- A range may not be the top-level result in v1; it must be consumed by a
  function or produces `#VALUE!`.
- Empty string is a valid string result. `null` is not a formula value.

Formatting remains display-only and applies to the computed stored value.

---

## Formula Language

### Lexical Rules

- Formula source begins with `=` after outer whitespace is trimmed.
- Function names, cell coordinates, Boolean literals, and named references are
  case-insensitive.
- String literals use double quotes. A literal double quote is written as `""`.
- Numeric literals use `.` as the decimal separator and may use exponent
  notation, for example `1.2e-4`. Thousands separators are not accepted.
- Whitespace outside strings is insignificant.
- Formula length is limited to 8,192 characters.
- Parenthesis nesting and function nesting are each limited to 64 levels.
- One evaluation may read at most 10,000 cells, and a range may cover at most
  10,000 grid positions. These limits are configurable server constants.

### Operators And Precedence

From highest to lowest precedence:

| Operators | Meaning |
|---|---|
| `()` | Grouping/function call |
| unary `+`, unary `-` | Numeric sign |
| `^` | Exponentiation, right-associative |
| `*`, `/`, `%` | Multiply, divide, remainder |
| `+`, `-` | Numeric addition/subtraction |
| `&` | String concatenation |
| `=`, `<>`, `<`, `<=`, `>`, `>=` | Comparison |

Boolean logic is provided by `AND`, `OR`, and `NOT`, not language operators.
Comparisons return Booleans. Numeric operators accept numbers only; there is no
implicit numeric parsing of strings. `&` converts scalar operands to canonical
text. String comparisons are case-insensitive ordinal comparisons in v1.

### Coordinate References

Coordinates use the shared Bullpen cell-reference helpers:

```text
A1      relative column, relative row
$A$1    absolute column, absolute row
$A1     absolute column, relative row
A$1     relative column, absolute row
```

The draft that preceded this proposal reversed relative and absolute notation;
the definitions above use standard spreadsheet semantics.

The `$` markers matter whenever a formula cell is copied or changes coordinate,
including paste, duplicate, drag, move, group move, and swap. They do not change
lookup during evaluation. A reference resolves only to a Value worker at that
coordinate. A blank grid position or a non-Value worker produces `#REF!` for a
direct reference.

Formula translation uses the formula cell's source and destination coordinates.
For displacement `(delta_col, delta_row)`, translate each reference component
independently:

```text
A1       translate column and row
$A1      keep column; translate row
A$1      translate column; keep row
$A$1     keep column and row
```

Range endpoints follow the same rule independently. Named references do not
change. Translation must replace coordinate-token spans rather than deparse and
reformat the AST: case, whitespace, punctuation, function spelling, and string
literals outside translated references remain byte-for-byte unchanged.

Moving a referenced Value worker does not rewrite formulas elsewhere;
coordinate references continue to mean worksheet coordinates. Moving the
formula cell itself does translate its relative and mixed coordinate references
by the formula cell's displacement, using the same rule as copy/paste.

### Named References

Names use the same case-insensitive lookup and deterministic duplicate-name
rules as ordinary Value interpolation.

- A simple name matching `[A-Za-z_][A-Za-z0-9_.]*` may appear bare, such as
  `tax_rate` or `build.counter`.
- Names containing spaces or operator punctuation use bracket syntax, such as
  `[tax rate]` or `[cost-per-unit]`.
- `]]` represents a literal `]` inside a bracketed name.
- A token that is a valid coordinate is always a coordinate, even if a Value
  worker has that name.
- A function name followed by `(` is always a function call.
- Duplicate names resolve to the first row-major match and attach a warning to
  the formula state. The warning does not fail calculation.
- Renaming or moving cells can therefore change name resolution. Stable worker
  IDs and explicit ID-based formula references remain deferred.

Examples:

```text
=A4 + tax_rate + counter
=A4 + [tax rate] + counter
=IF([release branch] = "main", 1, 0)
```

### Ranges

V1 supports rectangular coordinate ranges such as `A1:A12` and `B2:D8`.

- Range endpoints may use relative, absolute, or mixed syntax.
- Reversed endpoints normalize to the enclosing rectangle.
- A range contains only Value workers within the rectangle; blank positions
  and non-Value workers are represented as blanks to range-aware functions.
- Range order is row-major.
- A range creates dependencies on the covered coordinates, including currently
  blank coordinates. Creating, moving, or deleting a Value worker inside the
  rectangle dirties the formula.
- Named ranges and ranges between named cells are not supported.
- Direct arithmetic on ranges is an error. Aggregation and lookup functions
  define how they treat blanks, strings, and errors.

### Grammar Sketch

```text
formula      := "=" expression EOF
expression   := comparison
comparison   := concat (("=" | "<>" | "<" | "<=" | ">" | ">=") concat)*
concat       := additive ("&" additive)*
additive     := multiply (("+" | "-") multiply)*
multiply     := power (("*" | "/" | "%") power)*
power        := unary ("^" power)?
unary        := ("+" | "-") unary | primary
primary      := number | string | boolean | reference | range |
                function_call | "(" expression ")"
range        := coordinate ":" coordinate
function_call:= identifier "(" arguments? ")"
arguments    := expression ("," expression)*
```

Use a real tokenizer and parser. Do not translate formula text into Python or
JavaScript and call `eval`.

---

## Function Suite

Microsoft's published Excel function catalog and featured-function list are a
useful vocabulary baseline, but Bullpen should prioritize deterministic scalar
workflow calculations over breadth. The following are the recommended ten most
useful candidates in each category, not a claim of measured global popularity.

Reference catalogs:

- [Microsoft Excel functions by category](https://support.microsoft.com/en-us/excel/excel-functions-by-category)
- [Microsoft math and trigonometry functions](https://support.microsoft.com/en-us/excel/math-and-trigonometry-functions-reference)
- [Microsoft financial functions](https://support.microsoft.com/en-us/excel/financial-functions-reference)
- [Microsoft date and time functions](https://support.microsoft.com/en-us/excel/date-and-time-functions-reference)

### Candidate Catalog: Ten Per Category

| Category | Candidates |
|---|---|
| Math | `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `ABS`, `ROUND`, `ROUNDUP`, `ROUNDDOWN`, `MOD` |
| Financial | `PMT`, `PV`, `FV`, `NPV`, `IRR`, `RATE`, `NPER`, `IPMT`, `PPMT`, `SLN` |
| Engineering | `CONVERT`, `DELTA`, `GESTEP`, `DEC2BIN`, `DEC2HEX`, `DEC2OCT`, `BIN2DEC`, `HEX2DEC`, `OCT2DEC`, `COMPLEX` |
| String | `CONCAT`, `TEXTJOIN`, `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`, `LOWER`, `SUBSTITUTE` |
| Date/time | `DATE`, `TODAY`, `NOW`, `YEAR`, `MONTH`, `DAY`, `DAYS`, `EDATE`, `WORKDAY`, `NETWORKDAYS` |

Logical and error-handling functions are foundational even though they were not
one of the draft's five requested categories: `IF`, `IFS`, `AND`, `OR`, `NOT`,
`IFERROR`, `ISERROR`, `ISNUMBER`, `ISTEXT`, and `ISBLANK`.

### Recommended First Cut

Implement this smaller suite first:

```text
Math:       SUM AVERAGE MIN MAX COUNT ABS ROUND ROUNDUP ROUNDDOWN MOD
Logical:    IF AND OR NOT IFERROR ISERROR ISNUMBER ISTEXT ISBLANK
String:     CONCAT TEXTJOIN LEFT RIGHT MID LEN TRIM UPPER LOWER SUBSTITUTE
Date/time:  DATE TODAY NOW YEAR MONTH DAY DAYS
Financial:  PMT PV FV NPV
Engineering: CONVERT DELTA GESTEP
```

This first cut is large enough for common workflow formulas while avoiding
complex-number storage, iterative financial solvers, business-calendar policy,
and ambiguous date conventions. Add `IRR`, `RATE`, `NPER`, `IPMT`, `PPMT`,
`SLN`, base conversion, `EDATE`, `WORKDAY`, and `NETWORKDAYS` only after the
core evaluator has conformance tests.

Function contracts must be documented in a machine-readable registry containing
name, aliases, minimum/maximum arity, accepted types, volatility, and evaluator.
Function names are case-insensitive. Unknown functions produce `#NAME?`.

Date functions accept date/date-time values created by formula functions and
strict ISO date/date-time strings. They do not parse locale-formatted dates.

### Range And Coercion Rules

- `SUM`, `AVERAGE`, `MIN`, `MAX`, and `COUNT` flatten range arguments.
- Numeric scalar arguments are included.
- Numbers stored in Value cells are included; numeric-looking strings are not.
- Blank range positions and empty strings are ignored.
- Other strings and Booleans inside ranges are ignored by numeric aggregates;
  the same values passed as direct scalar arguments produce `#VALUE!`.
- `COUNT` counts numeric items only.
- Errors encountered in referenced formula cells propagate unless a containing
  `IFERROR` handles them.
- `IF`, `AND`, and `OR` short-circuit so an unused branch is not evaluated.
- `CONCAT` and `TEXTJOIN` flatten ranges in row-major order.

### Volatile Functions

`NOW()` and `TODAY()` are volatile in the sense that their previously computed
result can become stale without a Value write. In the first release they do
**not** create timers or automatic calculation schedules.

They evaluate only when:

- the formula is created or edited;
- another dependency change already causes that formula to recalculate;
- the workspace becomes active after being inactive; or
- a user or MCP client explicitly requests recalculation.

When the relevant time boundary passes, Bullpen may mark the formula stale but
must not recalculate it merely because the boundary passed. `NOW()` becomes
stale after the configured freshness interval, initially one minute. `TODAY()`
becomes stale at the next midnight in the workspace timezone. Staleness is UI
and read metadata; marking it must not write layout state, append history, fire
triggers, or broadcast a workspace mutation.

Workspace activation recalculation is one debounced, server-owned operation per
workspace. Opening several browser windows must not create one calculation per
window. The server coalesces simultaneous activation notices and skips the work
when the volatile cells are still fresh.

Clock-only recalculation does not append normal Value history or fire
value-change triggers by default, even when its result changes. A later explicit
per-workspace calculation schedule may opt into persistence and automation, but
that is a scheduler feature with its own cadence, coalescing, and loop controls;
it is not implicit behavior of `NOW()` or `TODAY()`.

`NOW()` uses server time and stores UTC. `TODAY()` derives the date using the
workspace timezone, falling back to the server timezone. Random functions are
not in v1 because they make persistence, history, tests, and triggers
surprising.

---

## Errors

User-facing error codes:

| Code | Meaning |
|---|---|
| `#PARSE!` | Invalid syntax or formula limit exceeded |
| `#NAME?` | Missing named reference or unknown function |
| `#REF!` | Invalid, missing, or out-of-bounds coordinate reference |
| `#VALUE!` | Wrong type, invalid scalar/range use, or disallowed result |
| `#DIV/0!` | Divide by zero or an empty average |
| `#NUM!` | Invalid numeric domain, overflow, or non-convergent calculation |
| `#CYCLE!` | Direct or indirect circular dependency |
| `#LIMIT!` | Evaluation exceeded cell, depth, time, or generation limits |

The card displays the short code and exposes the safe message in its tooltip,
config modal, and accessible description. Errors are values only inside the
evaluator; they are not stored in `value`.

If a formula previously succeeded and later fails:

- retain the previous `value` and `resolved_value_type`;
- set `formula_state.status: "error"` and persist the error;
- render the error code instead of the stale formatted value by default;
- allow the UI to reveal “last successful value” and timestamp;
- do not append a value-history entry or fire a value-change trigger; and
- include the formula-state change in the generation's single committed delta
  so clients visibly update.

If a formula has never succeeded, `value` is the empty string baseline and the
formula state distinguishes it from a successful empty result.

An upstream error propagates to dependents. Cells in a detected cycle receive
`#CYCLE!`; downstream cells receive the upstream error with a safe dependency
message. Independent formulas in the same generation continue calculating.

---

## Recalculation Semantics

### Single-Writer Calculation Architecture

Formula calculation is server-authoritative. The server is the only component
allowed to calculate and commit formula results. Browser clients may provide a
non-authoritative editor preview, but they never publish preview results or use
them as workspace state.

The following invariants are mandatory:

- A browser submits only a root intent, such as a constant write, formula-source
  edit, structural operation, or explicit recalculation request.
- Formula result fields and formula-state fields are read-only in every client
  write schema. The server rejects a client payload that attempts to set them.
- The server calculates the complete affected graph under the workspace
  mutation transaction and persists the resulting generation once.
- Intermediate formula results are neither persisted nor broadcast.
- Receiving a layout or calculation event never starts recalculation and never
  causes the client to send calculated values back to the server.
- Derived result staging uses an internal path that cannot invoke a root Value
  write handler or recursively start another generation.
- Each committed generation increments one authoritative workspace/layout
  revision and has one `calculation_id`.
- A client applies a generation only when its revision is newer than the last
  revision it has applied. Duplicate or older events are ignored.
- Concurrent root writes are serialized by the workspace lock and become
  distinct generations. They do not interleave.

The required sequence is:

```text
Window 1 ── root intent ──▶ Server
                            │
                            ├─ lock workspace
                            ├─ stage root mutation
                            ├─ calculate A → B → C internally
                            ├─ persist revision N once
                            └─ unlock workspace
                                      │
                         one committed-generation broadcast
                              ┌───────┴───────┐
                              ▼               ▼
                           Window 1        Window 2
                           render N        render N
                              │               │
                              └─ no writes back ─┘
```

An automation triggered after generation `N` may deliberately submit a new
root Value write. That creates a separately locked generation `N+1`; it is not
an echo of the calculation event. Existing cooldown and queue rules still
apply, and broader automation-cycle protection remains a separate concern.

### Dirtying Rules

A formula becomes dirty when:

- its source or declared result type changes;
- a directly or transitively referenced Value cell has a successful value
  write or changes formula state;
- a Value worker is created, deleted, moved, or renamed in a coordinate range
  or named-reference candidate set that the formula uses;
- a formula cell is copied or relocated and its relative refs are adjusted;
- a server-coalesced workspace activation finds a volatile result stale; or
- the user requests recalculation.

Formatting, units, icon, color, Save History, and unrelated worker metadata do
not dirty formulas.

### Calculation Generation

For each root mutation:

1. Acquire the workspace/layout mutation lock.
2. Validate and stage the root mutation according to the normal Value-write or
   structural-operation contract. Do not persist or broadcast it yet.
3. Parse changed formulas and extract direct coordinate, range, and name
   dependencies.
4. Discover affected formula cells. The first implementation may scan every
   formula in the workspace.
5. Resolve name/range membership against one consistent layout snapshot.
6. Build the affected dependency graph and find strongly connected components.
7. Mark cycles and topologically order the remaining formulas.
8. Evaluate each formula once against already-computed values from this
   generation and unchanged values from the snapshot.
9. Validate each successful result against its declared `value_type`.
10. Stage result and formula-state changes.
11. Persist the root mutation and complete derived generation together. Hold
    the lock, save once at the end, and restore the in-memory snapshot on
    failure. Partial generation persistence is not permitted.
12. Append history entries and produce value-change events for successful
    computed values that changed.
13. Increment the workspace revision and release the lock.
14. Emit one committed-generation broadcast containing a bounded delta or
    instructions to fetch revision state, then deliver value-change triggers in
    deterministic order.

Formula evaluation must not recursively invoke the ordinary write endpoint.
Use an internal staged-result path to prevent nested calculation generations.

### Brute-Force First Implementation

“Brute force” means scanning and reparsing all formula cells to discover the
affected subgraph. It does not mean repeatedly evaluating all formulas until
values stop changing. Every acyclic affected formula evaluates once per
generation in dependency order.

Initial safety limits:

- 5,000 formula cells per workspace;
- 10,000 referenced positions per formula;
- 25,000 evaluations per generation; and
- 2 seconds of evaluator CPU/wall budget per generation.

Exceeding a limit marks unevaluated affected cells `#LIMIT!`, leaves their last
successful values intact, and records a server warning. Limits should be
configuration constants and visible in diagnostics.

### Ordering

For deterministic history and triggers, formulas at the same topological depth
are processed in row-major coordinate order. A root write event precedes all
derived events. Derived events then appear in calculation order.

### Manual Recalculation

Provide:

- **Recalculate cell**: the selected formula and its downstream dependents;
- **Recalculate all**: every formula in the workspace; and
- MCP/API equivalents.

Manual recalculation always evaluates targeted formulas. It creates history and
value-change events only where the successful computed value changed, unless a
future explicit “fire on recalculation no-op” option is added.

---

## History And Value-Change Triggers

Formula source edits and computed result changes are distinct audit facts.

- A formula edit is a live formula entry. Record the new formula source in the
  formula audit metadata whether evaluation succeeds or fails. The source edit
  does not emit a separate value-change event; only a successful changed result
  does.
- Each successful computed result that differs in typed value from the prior
  successful result appends one normal Value history snapshot when Save History
  is enabled.
- Recalculation no-ops do not append normal value history.
- Formula errors and error recovery update formula audit metadata. Recovery
  appends value history only if the successful result differs from the last
  successful result.
- A calculation generation uses one `calculation_id`. History records and
  events include it plus `root_event_id`, `cause_ref`, and `changed_by`.
- Retention follows the existing Value history policy; do not create a second
  unbounded journal.

Successful changed results emit ordinary value-change events and may activate
`on_value_change` workers. Derived event metadata adds:

```json
{
  "changed_by": "formula",
  "calculation_id": "...",
  "root_event_id": "...",
  "formula_source": "=A1*1.05",
  "direct_dependencies": ["A1"]
}
```

These are internal post-commit trigger inputs, not per-cell Socket.IO
broadcasts. The generation's final cell states travel only in the one
committed-generation workspace event.

Trigger delivery happens only after the full calculation generation persists.
It must not run while the layout lock is held. One generation may trigger
multiple watched formula cells; existing per-worker cooldown and queue rules
still apply.

An unchanged computed result does not emit a formula-derived value-write event,
even when the existing root-write contract allows no-op triggers. This prevents
unrelated writes and volatile ticks from producing automation storms.

---

## Entry And Editing UI

### Entering A Formula

- Typing or pasting text beginning with `=` into a formula-aware Value editor
  proposes a formula.
- Enter saves and asks the server to parse, persist, and calculate.
- Escape cancels.
- A leading apostrophe, such as `'=A1+1`, stores the literal string `=A1+1`
  with the apostrophe removed.
- Replacing a formula with a non-`=` entry converts the cell to a constant
  after confirmation if the formula has dependents. The new constant write
  follows the normal Value transaction.
- The full config modal provides separate **Formula** and read-only **Last
  successful value** fields so source and result are never confused.

The inline editor shows formula source when editing and formatted computed value
when not editing. Formula cards display a small `fx` indicator. Error cards
show the error token and preserve access to the source and last good value.

### Point Mode

Point mode inserts coordinate references without leaving formula entry:

1. While the caret is at a location where an operand is valid, pressing an
   arrow key enters point mode and selects the adjacent grid cell; clicking a
   cell may also enter point mode.
2. Arrow keys move the reference selection. Shift+Arrow extends a rectangular
   range.
3. The editor previews the coordinate/range at the caret and highlights the
   referenced grid area.
4. `$` cycles relative/absolute modes for the active reference: `A1`, `$A$1`,
   `A$1`, `$A1`.
5. Enter inserts the reference and returns focus to formula editing. Escape
   cancels the point selection without cancelling the entire edit.
6. A second Escape while editing cancels the whole edit.

Point mode must not make worker cards draggable or mutate selection while it is
active. Screen-reader users can type refs directly and receive an accessible
description of the selected coordinate.

### Formula Assistance

- Autocomplete function names and Value names after the user types a prefix.
- Insert names containing spaces using bracket syntax.
- Show function signature, argument position, and concise help.
- Highlight references with stable colors in the source and on the grid.
- Show dependency and dependent lists in the config modal.
- Provide **Go to dependency** and **Go to dependent** actions.
- Warn, but allow saving, when a named reference resolves through the
  duplicate-name fallback.

---

## MCP And Server API

Extend existing Value tools rather than exposing evaluator internals.

```text
set_value(ref, value, value_type?)
set_formula(ref, formula, value_type?)
get_value(ref)
get_formula(ref)
recalculate_value(ref)
recalculate_all_values()
```

Rules:

- `set_value` with a normal string writes a constant, even if the JSON string
  begins with `=`. This preserves API clarity and prevents formula injection.
- `set_formula` requires a leading `=` and follows the formula transaction.
- `get_value` returns the last successful raw and formatted value plus formula
  status/error metadata. It must not return a stale value without indicating
  the error or stale state.
- `get_formula` returns source, status, safe error, last successful value,
  timestamps, resolved direct dependencies, and duplicate-name warnings.
- Recalculation responses include `calculation_id`, evaluated/changed/error
  counts, duration, and per-cell errors capped to a reasonable response size.
- MCP formula writes and recalculation use the same workspace lock, evaluator,
  persistence, history, event, and trigger path as UI operations.
- Existing authentication and workspace authorization apply.

Formula source is workspace-visible configuration and may expose sensitive
constants or names. Do not include it in unrelated ticket bodies or logs.

---

## Structural Operations

### Shared Translation Rule

Copy, paste, duplicate, drag, move, group move, and swap use one formula
translation operation. Given a formula cell's original coordinate and final
coordinate, apply the displacement to relative reference components and leave
absolute components fixed. A no-op placement has zero displacement and leaves
source unchanged.

Translation is derived entirely from the pre-operation layout and each cell's
final coordinate. Install the complete final layout before evaluating any
formula. This prevents operation order from changing group results.

If translation would move a reference before row 1 or column A, the affected
reference expression becomes the persisted structural error token `#REF!`; it
must not wrap or clamp. The parser accepts this token only as a structural error
expression, and evaluation records normal `#REF!` formula state while preserving
the last successful value. If either endpoint of a range becomes invalid, the
whole range expression becomes `#REF!`.

### Copy, Paste, And Duplicate

- Copying a formula cell starts from its stored formula source and adjusts
  relative coordinate components by destination displacement.
- Absolute components do not move.
- Named references do not change.
- Copying a group treats each copied formula relative to its own source and
  destination.
- Pasted formulas calculate after the entire paste batch exists, not once per
  cell, so intra-batch references see the completed batch.
- Newly created structural copies, including paste and duplicate, create
  baseline history according to the existing Value lifecycle contract and do
  not fire initial value-change triggers.

### Drag, Move, Group Move, And Swap

- Dragging is a relocation, but formula translation is intentionally identical
  to copy/paste translation. A formula moved from C38 to D38 rewrites
  `=SUM(C36:C37)` to `=SUM(D36:D37)`.
- Every relocated formula translates from its own pre-operation coordinate to
  its own final coordinate. In a swap, both formula cells translate; in a group
  move, each member uses the same group displacement only when its actual source
  and destination imply that displacement.
- Moving a referenced cell does not rewrite coordinate references in other
  formulas. Those formulas are dirtied against the old and new layouts and
  resolve the same coordinate source against the final layout.
- Name references do not translate. Moves that can change name resolution dirty
  the affected candidate set.
- The server installs all final coordinates and translated sources, calculates
  one affected dependency graph, persists once, and emits one committed
  generation broadcast. Intermediate layouts and results are never observable.
- Successful changed results from relocating existing cells follow ordinary
  formula history and post-commit trigger rules. An unchanged result creates no
  value history or trigger even when structural translation changed source.

This translation rule does not change aggregate blank handling. In the C38 to
D38 example, if D36:D37 is empty, `SUM(D36:D37)` evaluates to `0`; it is not a
`#VALUE!` error. Direct reference to an empty coordinate remains `#REF!`, and
other empty aggregate contracts remain as defined under Range And Coercion.

### Import, Export, Teams, And Backup

- Current-schema snapshots preserve formula source, version, last successful
  value, and formula state.
- After load/import, Bullpen validates and recalculates formulas once the full
  layout is present. It does not trust imported computed results as current.
- Import errors remain local to affected cells and do not reject otherwise
  valid workers unless the container format itself is invalid.
- Exported tabular text defaults to displayed computed values. A formula-aware
  worksheet export may explicitly export source.
- Team templates may preserve source but should clear environment-specific
  calculation timestamps and mark results stale until instantiated.
- Backup restore preserves audit/history and performs a validation
  recalculation without firing value-change triggers.

### Delete And Convert

Deleting or converting a referenced Value worker is allowed after a warning
that lists direct dependents. Dependents recalculate to `#REF!` or `#NAME?`.
Deleting a formula cell requires no special dependent handling beyond the same
warning. There is no cascade delete.

---

## Collaboration And Events

The single-writer calculation architecture is the collaboration contract, not
an implementation preference. A formula save returns the accepted source,
committed workspace revision, and calculation id. Clients replace optimistic
editor state with that server result.

One calculation generation produces exactly one workspace mutation broadcast:

```text
formula:calculation_committed
```

Do not also emit per-cell `formula:state_updated` events or a second
`layout:updated` event for the same generation. If existing client architecture
requires the standard layout event name, use `layout:updated` as the sole
generation event instead and add the calculation metadata to it. The invariant
is one committed generation, one broadcast—not a particular event name.

The payload includes:

```json
{
  "workspace_id": "...",
  "workspace_revision": 42,
  "calculation_id": "...",
  "root_event_id": "...",
  "evaluated_count": 12,
  "changed_count": 4,
  "error_count": 1,
  "duration_ms": 18,
  "changes": []
}
```

`changes` is a bounded authoritative delta containing final root, formula
result, and formula-state changes. It never contains intermediate evaluation
state. If the delta exceeds the payload limit, omit it and tell clients to fetch
the complete state for `workspace_revision`.

Every connected window receives the same broadcast and only renders it. Client
event handlers must not call formula evaluation, request recalculation, write a
formula result, or echo the event. A browser-side formula preview is discarded
or replaced when the committed revision arrives and is never propagated.

Clients track the last applied workspace revision:

- revision greater than local: apply the delta or fetch the snapshot;
- revision equal to local: ignore as a duplicate;
- revision lower than local: ignore as stale; and
- revision gap: fetch authoritative workspace state rather than replaying local
  calculations.

Opening or focusing multiple windows may send multiple workspace-activation
notices. Those notices are hints, not mutations. The server debounces them by
workspace and may produce at most one volatile recalculation generation when
the current volatile results are stale.

Simultaneous writes from different windows are serialized at the server. Each
accepted write gets its own later revision and generation; clients never merge
formula results themselves.

---

## Security, Reliability, And Performance

- Implement an allowlisted AST evaluator with no dynamic property access,
  imports, reflection, callbacks, or host-language evaluation.
- Validate formula length, nesting, argument count, range size, dependency
  count, generation count, and time budget before or during evaluation.
- Keep function implementations pure except the explicitly controlled clock
  read used by volatile date/time functions.
- Never fetch URLs, read environment variables, inspect tickets, or execute
  worker commands from a formula.
- Escape formula source and error messages in HTML.
- Avoid CSV formula injection when exporting displayed strings: use the
  existing export policy and explicitly distinguish “export values” from
  “export formulas.”
- Log calculation id, duration, counts, limit violations, and internal error
  correlation id. Do not log full formula source at normal levels.
- A parser/evaluator crash fails the affected cell safely, preserves previous
  values, restores staged state, and does not terminate the Bullpen server.
- Calculation runs under the workspace mutation lock initially. If latency
  becomes material, move pure evaluation outside the lock only with a layout
  revision check and retry-on-conflict design.

---

## Accessibility

- Announce a card as “Formula Value,” its displayed result or error, and stale
  status.
- Associate parser errors with the formula input and identify the character
  position when safe.
- Make autocomplete, point mode, dependency navigation, and reference-mode
  cycling fully keyboard accessible.
- Do not use reference highlight color as the only association; include a
  symbol or numbered label.
- Respect reduced-motion settings during recalculation and reference
  highlighting.

---

## Testing And Acceptance Criteria

### Parser And Evaluator

- Golden tests for every grammar production, operator precedence rule, literal,
  ref form, range form, and error code.
- Property/fuzz tests proving arbitrary input cannot escape the parser, hang the
  process, or produce non-finite stored numbers.
- Table-driven conformance tests for every function, arity, type rule, blank
  behavior, range behavior, boundary, and error.
- Explicit tests for case folding, Unicode names, bracket escaping, duplicate
  names, coordinate precedence, and formula limits.

### Dependency And Recalculation

- Direct, branching, diamond, deep-chain, and independent graphs.
- Self-cycle, multi-cell cycle, cycle with downstream dependents, and cycle
  recovery.
- Root constant writes, formula edits, errors, recovery, volatile ticks,
  rename/move/create/delete, and range membership changes.
- Deterministic row-major ordering at equal graph depth.
- One evaluation per affected acyclic cell per generation.
- Persistence failure restores staged results and emits no triggers.
- A root write plus all derived results performs one locked persistence save and
  produces one committed workspace revision.
- Client attempts to write computed `value` or `formula_state` fields are
  rejected without mutation.
- Derived staging cannot re-enter root write handlers or recursively create a
  calculation generation.

### Lifecycle

- Copy, paste, duplicate, single drag, group drag, and swap adjustment for all
  four relative/absolute combinations and both endpoints of ranges.
- Paired copy-versus-drag fixtures proving that the destination formula source,
  formula state, and computed result are identical for the same source and
  destination; only source-cell retention and structural audit facts differ.
- Source-preservation tests proving that translation changes coordinate tokens
  only, including formulas with whitespace, lowercase function names, and
  punctuation-heavy string literals.
- Boundary translation to structural `#REF!`, plus recovery after a later
  source edit.
- Multi-cell paste calculation after batch completion.
- Atomic final-layout calculation for moves and swaps, including formulas that
  move with referenced cells, move into self-reference/cycles, or affect range
  membership at old and new coordinates.
- Import/export, teams, backup restore, and legacy leading-`=` strings.
- Formatting and interpolation always use the successful computed value and
  clearly surface stale/error status where relevant.
- History contains changed successful results only; formula audit captures
  source/error changes; retention remains bounded.
- Value-change triggers run after commit, once per changed formula result, and
  never for formula errors or unchanged volatile results.

### UI And Browser

- Inline edit, literal apostrophe, autocomplete, error position, `fx` state,
  last-good-value reveal, and conversion warning.
- Point mode by keyboard and pointer, range extension, `$` cycling, nested
  Escape behavior, and grid drag suppression.
- Two-client collaboration sees identical source, result, error, and timestamps.
- Two or more clients receiving one committed-generation event do not evaluate
  formulas, call recalculation endpoints, or emit result writes.
- Duplicate, stale, and revision-gap event handling follows the collaboration
  contract and never uses local calculation to repair state.
- Multiple simultaneous workspace-activation notices coalesce into at most one
  server calculation generation.
- One generation emits exactly one workspace mutation broadcast, regardless of
  the number of changed formula cells or connected windows.
- Clock passage alone creates no persisted mutation, history, trigger, or
  broadcast for `NOW()` or `TODAY()`.
- Real-browser tests cover reference highlighting and accessibility names.

### Performance

Acceptance dataset:

- 5,000 Value cells, including 1,000 formulas;
- a chain depth of 500;
- a 100-by-100 sparse range; and
- a root change affecting 500 formulas.

On supported development hardware, the 500-formula generation should complete
within the configured 2-second budget, keep the server responsive, persist once,
and emit a bounded event payload. Record actual benchmarks rather than making a
cross-machine millisecond guarantee.

### Functional Acceptance

Formula support is ready when:

- formulas can be created, edited, copied, relocated, loaded, and recalculated
  through UI and MCP;
- results are identical across those entry paths;
- cycles and failures never overwrite the last successful value;
- successful derived changes integrate with formatting, history,
  interpolation, collaboration, and triggers;
- the evaluator cannot execute host code or exceed configured limits; and
- all parser, function, lifecycle, trigger, browser, and performance suites pass.

---

## Phased Implementation

### Phase 0 — Contract And Conformance Fixtures

- Encode the accepted P0 and architecture decisions in conformance fixtures.
- Define grammar, error codes, type/coercion tables, and function registry.
- Build shared JSON fixtures for parser/evaluator behavior.
- Characterize existing Value write, history, trigger, and layout locking paths.

### Phase 1 — Scalar Parser And Evaluator

- Add formula fields and normalization.
- Implement tokenizer, parser, AST, safe evaluator, scalar coordinate/name refs,
  operators, errors, and core logical/math functions.
- Add `set_formula`, `get_formula`, and formula-aware reads.
- Support direct editing without point mode or ranges.

### Phase 2 — Dependency Recalculation

- Extract dependencies, scan affected formulas, build per-generation graph,
  detect cycles, topologically evaluate, stage, and persist once.
- Integrate history, events, interpolation, and post-commit triggers.
- Add manual recalculate commands and diagnostics.

### Phase 3 — Ranges And Function Suite

- Add rectangular ranges and range limits.
- Complete the recommended first-cut function suite.
- Add volatile staleness, workspace timezone, and coalesced activation behavior
  without an automatic calculation timer.

### Phase 4 — Formula Editing UX

- Add `fx` states, autocomplete, signatures, errors, last-good display,
  dependency navigation, and point mode.
- Add accessible reference highlighting and browser tests.

### Phase 5 — Structural Lifecycle And Optimization

#### Tranche 5A — Translation Core And Conformance

- Implement token-span coordinate translation without reformatting unrelated
  formula source.
- Cover scalar/range references, relative/absolute/mixed components, negative
  boundaries, structural `#REF!`, strings containing coordinate-like text, and
  exact source preservation.
- Keep this tranche pure and deterministic: no persistence, events, or layout
  mutation.

#### Tranche 5B — Single-Cell Structural Transactions

- Integrate the shared translator with single-cell drag/move, duplicate, and
  paste.
- Build one server-owned generation from the final layout, including formulas
  affected at old and new coordinates.
- Verify history, formula audit, triggers, one-save/one-broadcast behavior,
  error preservation, and rollback.

#### Tranche 5C — Group Moves, Swaps, Duplicate, And Paste

- Translate every formula from the pre-operation layout to its final coordinate
  before evaluation.
- Cover group drag, occupied-cell swap, duplicate group, rectangular paste,
  moving a formula with its precedents, intra-group dependencies, cycles, and
  order independence.
- Persist and broadcast only the complete final generation.

#### Tranche 5D — Remaining Structural Lifecycle

- Complete dirtying for create, delete, convert, rename, and movement into or
  out of coordinate ranges and named-reference candidate sets.
- Complete import, team, transfer, backup-restore, and dependency-warning
  behavior using the same final-layout calculation boundary.
- Add browser coverage for drag source translation and visible recalculation.

#### Tranche 5E — Optimization And Final Verification

- Benchmark representative workspaces and structural batches.
- Add an in-memory reverse dependency index only if scanning no longer meets the
  budget. Treat it as rebuildable cache, not persisted truth.
- Run parser, evaluator, lifecycle, collaboration, trigger, rollback, browser,
  and performance suites before declaring structural work complete.

---

## Decision Issues, Prioritized

### Accepted P0 Decisions

1. **Formula result model — accepted.** `formula.source` is authoritative input,
   `value` is the last successful result, and persisted `formula_state` carries
   errors. Error tokens are not stored in `value`.
2. **History and trigger semantics — accepted.** Derived history and events are
   changed-success-only. Trigger delivery occurs after the complete generation
   commits. Errors and recalculation no-ops do not trigger automation.
3. **Name syntax and ambiguity — accepted.** Formulas support bare simple names
   and bracketed names with spaces. Coordinates take precedence, and duplicate
   names use the existing row-major fallback with a warning.
4. **Range scope — accepted.** Rectangular coordinate ranges are part of the
   first public formula release, delivered in Phase 3 after scalar formulas.
5. **Result types and date model — accepted.** Results use finite numbers,
   strings, internal Booleans/ranges, ISO date strings, and no Excel serial
   dates.
6. **Atomic generation boundary — accepted.** A root mutation and all derived
   results persist as one locked generation and one save, with rollback on
   failure. Partial generations are prohibited.
7. **Original copy/move reference semantics — superseded.**
   The original decision made copy use standard `$` behavior while move
   preserved formula source. The proposed P0 revision below replaces that
   distinction and is accepted below.
8. **Evaluator limits — accepted.** Formula, nesting, range, dependency,
   generation, and time limits are required, with `#LIMIT!` preserving the last
   successful value.

### Accepted P0 Revision

1. **Unified copy/relocation translation.** Copy, paste, duplicate, drag, move,
   group move, and swap use the same standard `$` translation based on each
   formula cell's source and destination coordinates. Moving a referenced cell
   still does not rewrite formulas elsewhere; it dirties affected formulas
   against the final layout.
2. **Blank range behavior remains unchanged.** Relocating C38 to D38 translates
   `=SUM(C36:C37)` to `=SUM(D36:D37)`. If D36:D37 is empty, the result is `0`,
   not `#VALUE!`. Changing that result would be a separate aggregate-function
   compatibility decision.
3. **Out-of-bounds translation is persisted.** A translated coordinate or
   range that crosses above row 1 or before column A becomes structural
   `#REF!` source, evaluates as `#REF!`, and preserves the last successful
   value.

### Additional Accepted Architecture Decisions

1. **Single server writer — accepted.** Only the server calculates and commits
   formula results. Clients submit root intents and render committed revisions.
2. **One generation broadcast — accepted.** A committed generation produces one
   workspace mutation broadcast with a revision and calculation id. There are
   no intermediate or per-cell result broadcasts.
3. **No event feedback — accepted.** Client event handlers never calculate,
   request recalculation, publish results, or echo calculation events.
4. **Conservative volatility — accepted.** `NOW()` and `TODAY()` have no implicit
   timer in the first release. Stale results recalculate on formula/dependency
   work, coalesced workspace activation, or explicit request. Clock-only
   recalculation does not journal or trigger automation by default.

### P1 — Decide Before The First Public Release

1. **Function cut.** Confirm the recommended suite and exact per-function
   coercion/error contracts. Financial and date functions are the largest
   compatibility risk.
2. **Error display versus stale value.** This proposal renders the error and
   exposes the last successful value on demand. An alternative is to display
   stale data with a warning, but that risks users treating it as current.
3. **Formula audit representation.** Decide whether existing Value history can
   carry formula-source/error metadata cleanly or needs a bounded parallel
   formula audit list.
4. **Structural bootstrap triggers.** Confirm that paste/import/team/restore
   calculate but suppress initial derived triggers, matching existing structural
   Value lifecycle semantics.
5. **MCP formula injection boundary.** Confirm that `set_value("=...")` remains
   literal and only `set_formula` creates executable formula content.
6. **Duplicate-name warnings.** Decide where warnings appear and whether a
   workspace policy may upgrade ambiguous names from warning to `#NAME?`.
7. **Workspace limits and diagnostics.** Choose whether limits are fixed,
   configuration-backed, or workspace policy, and expose enough diagnostics for
   users to remediate failures.

### P2 — Can Follow The First Release

1. Stable ID-based references that survive moves and renames.
2. Indexed reverse dependencies and incremental AST caching.
3. Named ranges and structured/table references.
4. Additional financial, engineering, date, lookup, and statistical functions.
5. Formula-source export/import compatible with external spreadsheets.
6. Calculation inspection: trace precedents, trace dependents, and step-through
   evaluation.
7. Explicit per-workspace scheduled volatile calculation modes.
8. Protected/locked formula cells and finer MCP write permissions.
9. Width-aware array/spill results, if Bullpen ever adopts multi-cell results.
10. Durable layout revisions and optimistic calculation outside the mutation
    lock for very large workspaces.

---

## Decision Record Summary

The accepted decisions require scalar formulas and the dependency engine before
ranges and point mode, while keeping the grammar and model compatible with both.
Formula calculation is a single-writer server transaction that produces
ordinary Value results. It preserves last successful values on error while
making stale/error state visible, commits a complete calculation generation
once, broadcasts it once, and only then delivers eligible automation triggers.
