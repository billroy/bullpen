# Formula Point Mode And Function Help

## Status

Proposed.

## Summary

Bullpen formulas accept coordinate references and rectangular ranges such as
`C36` and `C36:C37`, but users currently have to type those references. Add a
spreadsheet-style point mode that lets a user insert a cell or range while
creating or editing a formula:

- use an arrow key at a valid reference position to select a nearby cell;
- click a grid cell to insert its reference;
- drag across cells, or use Shift+Arrow, to select a rectangular range;
- preview and highlight the selected reference before insertion; and
- return to the formula editor without saving the formula prematurely.

Also add contextual formula help during the same edit cycle:

- searchable function library;
- function-name completion;
- current function signature and active argument help; and
- concise descriptions and examples generated from one server-owned catalog.

This is an editing feature only. It does not change formula syntax, parsing,
calculation, persistence, or range semantics.

---

## Confirmed Current Behavior

Point mode is described aspirationally in `value-cell-formulas.md`, but it is
not implemented.

The current UI has three formula-entry surfaces:

1. the inline Value-card editor;
2. the compact Value-card editor, which may include a `name/unit:` prefix; and
3. the empty-cell Value shortcut editor.

The worker configuration modal also exposes a plain Formula input.

Current implementation behavior:

- these editors are ordinary text inputs;
- arrow key events are stopped from reaching the worksheet while the input has
  focus, but they only move the text caret;
- clicking a worker card follows normal card selection/action behavior;
- dragging on the grid performs ordinary worksheet selection, panning, or
  worker dragging;
- losing editor focus cancels the inline edit;
- no point-mode session or reference-selection state exists;
- no coordinate/range preview is inserted at the caret;
- no referenced-cell overlay is rendered;
- no function catalog, autocomplete, signature help, or formula-help panel is
  exposed; and
- existing frontend and browser tests cover typed formulas and typed ranges,
  not point-selected references.

The parser and evaluator already support the syntax needed by this proposal,
including absolute markers and rectangular ranges. The missing work is editor
and grid interaction.

---

## Goals

- Insert single-cell references without typing coordinates.
- Select rectangular ranges with keyboard or pointer input.
- Support ranges in function arguments, for example creating
  `=SUM(C36:C37)` from `=SUM(`.
- Preserve the user's formula text, caret, and unsaved edits throughout point
  selection.
- Keep grid pointing distinct from ordinary worksheet selection and worker
  dragging.
- Support relative and absolute reference forms.
- Provide function discovery and argument help without leaving formula entry.
- Use one authoritative catalog for every function the evaluator supports.
- Make the workflow keyboard-accessible and screen-reader understandable.
- Cover both formula creation and re-editing.

## Non-Goals

- No formula grammar or evaluator change.
- No non-rectangular or multi-area references.
- No union syntax such as `A1:A3,C1:C3` as one range value.
- No structured table references.
- No automatic repair of invalid formulas.
- No client-side formula evaluation.
- No change to relative-reference translation during drag, copy, or paste.
- No dependency-graph visualization in this feature.
- No point selection while the full worker configuration modal remains open in
  the first implementation; the modal receives function help but grid pointing
  remains an inline worksheet workflow.

---

## Terminology

- **Formula edit session**: one unsaved formula creation or re-edit operation.
- **Point mode**: a temporary substate of formula editing in which grid
  navigation changes a reference preview instead of worksheet selection.
- **Anchor**: the first coordinate of a point selection.
- **Focus coordinate**: the current moving end of the selection.
- **Reference span**: the source-text range that the preview will insert or
  replace.
- **Reference preview**: the temporary `A1` or `A1:B3` text shown in the
  formula editor while point mode is active.
- **Formula assistance**: function completion, signature help, and library UI.

---

## Functional Proposal

### Formula Edit Session

Use one explicit formula edit session for worksheet formula entry. It stores:

```text
editor kind: existing Value | compact Value | empty-cell shortcut
target coordinate and slot, if one exists
formula source
non-formula compact prefix, if any
selectionStart and selectionEnd
original formula source
dirty state
point-mode state, if active
formula-help state
```

The formula source is separate from a compact editor's optional `name/unit:`
prefix. Point-mode offsets are always relative to formula source, so a colon in
`name/unit:=SUM(A1:A3)` cannot be confused with the range colon.

Only one formula edit session may exist in a worksheet at a time.

### Entering Formula Editing

Existing entry gestures remain:

- create a Value in an empty selected cell and type `=`;
- click/double-click an existing Value to edit it; or
- re-edit a formula Value and receive its exact stored source.

Point mode is available only after the edit text is a formula beginning with
`=`. A constant Value edit retains current keyboard and mouse behavior.

Starting a formula edit shows:

- the formula input;
- a small **Select cells** crosshair button;
- an `fx` function-help button; and
- contextual signature help when the caret is inside a supported function.

### Valid Reference Insertion Context

Point mode may begin only where a reference expression is syntactically
plausible. Examples include:

- immediately after `=`;
- after `(` or `,`;
- after a binary or comparison operator;
- after a unary operator where its operand is expected;
- over a selected existing coordinate or range token; and
- at the range endpoint after `:`.

It must not begin:

- inside a quoted string;
- inside a bracketed Value name;
- in the middle of a number, identifier, or function name;
- immediately after a complete operand where an operator is required; or
- outside the formula portion of a compact editor.

A small client-side lexical helper determines this context. It need not parse
or evaluate the complete formula, but it must recognize strings, escaped
quotes, bracketed names, coordinates, identifiers, punctuation, operators, and
parenthesis nesting.

When point mode is unavailable, arrow keys retain normal text-caret behavior
and **Select cells** is disabled with an explanatory tooltip.

### Entering Point Mode With The Keyboard

At a valid insertion context:

- ArrowUp selects the cell above the formula cell;
- ArrowDown selects the cell below it;
- ArrowLeft selects the cell to its left; and
- ArrowRight selects the cell to its right.

This first arrow enters point mode. The formula cell is the origin even if the
grid's prior worksheet selection is elsewhere.

If the requested coordinate falls outside the writable grid, do not enter
point mode and announce that the grid boundary was reached.

### Keyboard Selection In Point Mode

While point mode is active:

- Arrow moves both anchor and focus, preserving a one-cell selection;
- Shift+Arrow keeps the anchor and moves the focus, producing or resizing a
  rectangle;
- Home/End and PageUp/PageDown are not intercepted in v1;
- the viewport pans as necessary to keep the focus coordinate visible;
- Enter commits the preview and returns focus to formula editing;
- Tab also commits the preview and returns to formula editing;
- Escape cancels the preview and restores the pre-point formula text and
  selection;
- a second Escape, after point mode has ended, cancels the whole formula edit
  according to existing behavior; and
- typing an operator, comma, or closing parenthesis commits the preview,
  inserts that character, and continues formula editing.

Enter while point mode is active inserts the reference; it does not save the
formula. A later Enter from normal formula editing saves the completed formula.

### Pointer Selection

While a formula edit session is active at a valid insertion context:

- clicking a grid cell inserts that cell's reference and returns focus to the
  editor;
- pointer-down and drag across the grid previews the rectangular range from
  the starting cell to the current cell;
- pointer-up commits that range and returns focus to the editor;
- dragging may begin on occupied or empty cells;
- moving near the viewport edge pans the grid at a bounded rate; and
- pointer cancellation cancels the preview without cancelling formula edit.

Point-mode pointer handling takes precedence over normal grid behavior. During
the gesture:

- worker cards are not draggable;
- card buttons and menus do not open;
- ordinary single/multiple worksheet selection does not change;
- worker connection handles and resize handles do not activate;
- empty-cell creation does not activate; and
- editor blur does not cancel the formula session.

The grid handles point-mode pointer events at its capture boundary so occupied
cards and empty cells behave consistently.

### Range Rendering

Normalize the rectangle to its top-left and bottom-right coordinates when
rendering source text:

```text
single cell: C36
range:       C36:E40
```

The anchor may be below or to the right of the focus during selection; source
text still uses normalized rectangle order.

Point mode permits empty cells inside or at the edge of a range. It also
permits selection of the formula's own cell. Normal server evaluation remains
authoritative and may subsequently return `#REF!` or `#CYCLE!`.

### Reference Preview And Source Editing

When point mode begins, capture:

- formula text before the reference span;
- formula text after it;
- the original selected text; and
- the original caret/selection.

As the grid selection changes, render:

```text
prefix + current_reference + suffix
```

Do not repeatedly parse and splice the already-previewed string. This prevents
old preview text from accumulating as a range changes.

If the user selected an existing reference such as `C36:C37` before entering
point mode, the preview replaces that complete token. Otherwise it inserts at
the caret or replaces the ordinary text selection.

Cancelling point mode restores the exact original formula text and selection.

### Relative And Absolute References

New point selections begin as relative references.

While point mode is active, `$` or F4 cycles the selected reference through:

```text
A1 -> $A$1 -> A$1 -> $A1 -> A1
```

For a range, apply the same mode to both endpoints:

```text
A1:B3 -> $A$1:$B$3 -> A$1:B$3 -> $A1:$B3 -> A1:B3
```

The cycle changes only the preview. It does not move the anchor or focus.

### Formula Save And Cancellation

Normal formula-edit state:

- Enter validates locally as today and submits the complete formula;
- Escape restores the original cell and ends editing;
- clicking outside ends editing according to existing policy; and
- a server parse/evaluation error is displayed through the existing formula
  state after save.

Point-mode state:

- Enter/Tab commits only the reference;
- Escape cancels only point mode;
- pointer selection commits on pointer-up; and
- clicking outside the selected grid gesture must not implicitly save or
  cancel the formula.

### Visual Feedback

While point mode is active:

- selected cells receive a distinct formula-reference outline and translucent
  fill;
- the anchor and focus are distinguishable for a range;
- the formula editor shows the same reference text being highlighted;
- the formula cell remains visibly identified as the edit target;
- the cursor changes to a crosshair over selectable grid cells; and
- a compact hint reads, for example,
  `Selecting C36:C37 — Enter to insert, Esc to cancel`.

Point-mode highlighting must be independent of ordinary worksheet selection so
entering or cancelling point mode does not destroy the user's prior selection.

---

## Function Library And Contextual Help

### Authoritative Function Catalog

Create one server-owned catalog for every supported evaluator function. Each
entry contains:

```json
{
  "name": "SUM",
  "category": "Math and aggregation",
  "signature": "SUM(value1, [value2], ...)",
  "summary": "Adds numeric values and ranges; ignores blanks and text.",
  "arguments": [
    {"name": "value1", "description": "First number, cell, or range."},
    {"name": "value2", "optional": true, "repeatable": true,
     "description": "Additional numbers, cells, or ranges."}
  ],
  "examples": ["=SUM(A1:A10)", "=SUM(A1, C1:C3)"],
  "accepts_ranges": true
}
```

The initial catalog covers the complete implemented library:

- Logic and tests: `IF`, `IFERROR`, `ISERROR`, `AND`, `OR`, `NOT`,
  `ISNUMBER`, `ISTEXT`, `ISBLANK`;
- Math and aggregation: `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `ABS`,
  `ROUND`, `ROUNDUP`, `ROUNDDOWN`, `MOD`, `DELTA`, `GESTEP`;
- Text: `CONCAT`, `TEXTJOIN`, `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`,
  `LOWER`, `SUBSTITUTE`;
- Date and time: `DATE`, `YEAR`, `MONTH`, `DAY`, `DAYS`, `NOW`, `TODAY`;
- Conversion: `CONVERT`; and
- Financial: `PV`, `FV`, `PMT`, `NPV`.

Tests must fail if the evaluator supports a function without a catalog entry or
the catalog advertises a function the evaluator does not support.

### Opening Help

Formula assistance is available through:

- the `fx` button beside a formula editor;
- F1 while formula editing;
- Ctrl+/ or Cmd+/ while formula editing; and
- automatic completion after typing a function-name prefix.

The `fx` button and shortcuts open a small panel anchored near the editor. It
does not cancel formula entry or move the grid selection.

### Function Completion

When the caret is at an identifier position and the user types letters:

- show matching function names, ordered by prefix match then alphabetically;
- display the signature and one-line summary for the highlighted result;
- ArrowUp/ArrowDown moves within results;
- Enter or Tab inserts `FUNCTION(`;
- clicking a result performs the same insertion;
- Escape closes completion without cancelling formula edit; and
- continued typing filters the list.

Completion is case-insensitive and inserts the catalog's uppercase name.
Completion does not activate inside strings, bracketed names, or existing
coordinate references.

### Signature And Argument Help

When the caret is inside a known function call, display:

- its signature;
- the current argument highlighted;
- the argument's short description; and
- whether that argument accepts a cell or range.

A lightweight nesting scanner determines the innermost function and argument
index by tracking parentheses and commas while ignoring strings and bracketed
names. It must handle nested calls such as:

```text
=IF(ISERROR(A1), SUM(B1:B4), ROUND(C1, 2))
```

Signature help follows the innermost call containing the caret. It stays
visible during point mode so a user selecting `B1:B4` can still see that the
current `SUM` argument accepts a range.

### Searchable Library

The full help panel includes:

- search by name, category, or summary text;
- category grouping;
- signature, argument descriptions, and examples;
- an **Insert function** action; and
- an indication for functions that accept ranges.

Inserting from the library replaces the current function-name prefix or
inserts `FUNCTION(` at a valid expression position. The panel then closes and
focus returns to the formula editor.

The worker configuration modal receives the same completion, signature, and
library help. Point selection itself remains an inline worksheet interaction
in v1 because the modal obscures and disables the grid.

### Catalog Delivery

Expose the read-only catalog to the browser through a small server endpoint or
existing workspace bootstrap payload, and to agents through the Bullpen MCP
`list_formula_functions` tool. It is application metadata, not workspace
state, and requires no persistence or invalidation protocol.

The frontend may hold the catalog in memory for the page lifetime. Failure to
load it disables assistance with a non-blocking message; formula typing and
saving continue to work.

---

## Accessibility

- Announce entry into and exit from point mode.
- Announce the current cell or normalized range after every keyboard move.
- Identify whether the reference is relative, absolute, row-absolute, or
  column-absolute.
- Use the existing polite live region for grid-selection announcements.
- The function completion popup uses combobox/listbox semantics.
- The library panel is keyboard navigable and returns focus to the editor when
  closed.
- Signature help is associated with the input through `aria-describedby` and
  announced only when function or argument context changes.
- Reference highlighting cannot rely on color alone; use an outline and an
  accessible text description.
- Screen-reader users may always type references directly without entering
  point mode.

---

## Technical Proposal

### Ownership

`BullpenTab` owns the worksheet-level formula edit session because it already
owns grid coordinates, viewport movement, pointer selection, and keyboard grid
navigation.

`WorkerCard` becomes a presentation surface for an existing-cell session:

- it requests the session on edit start;
- it renders the session source supplied by `BullpenTab`;
- it reports input text and selection changes; and
- it requests commit or cancellation.

The empty-cell shortcut uses the same session rather than a separate point-mode
implementation. Compact editor name/unit parsing occurs before the formula
session begins and after it commits.

This creates one point-mode state machine rather than parallel card, compact,
and shortcut implementations.

### Suggested Session Shape

```javascript
formulaEditSession: {
  kind: 'worker' | 'compact' | 'shortcut',
  slot: 12,
  coord: { col: 2, row: 37 },
  originalSource: '=SUM(C36:C37)',
  source: '=SUM(C36:C37)',
  prefix: '',
  selectionStart: 5,
  selectionEnd: 12,
  point: null,
  assistance: {
    completionOpen: false,
    selectedFunction: null,
    activeFunction: null,
    activeArgument: null,
    libraryOpen: false,
  },
}
```

Point state:

```javascript
point: {
  anchor: { col: 2, row: 35 },
  focus: { col: 2, row: 36 },
  referenceMode: 'relative',
  replaceStart: 5,
  replaceEnd: 12,
  prefixSource: '=SUM(',
  suffixSource: ')',
  originalSource: '=SUM(C36:C37)',
  originalSelectionStart: 5,
  originalSelectionEnd: 12,
  inputMethod: 'keyboard' | 'pointer',
}
```

This is transient component state. Nothing is persisted until normal formula
save.

### Lexical Helpers

Add small, pure frontend helpers for:

```text
formulaReferenceContext(source, selectionStart, selectionEnd)
formulaReferenceSpanAt(source, selectionStart, selectionEnd)
formulaFunctionPrefixAt(source, caret)
formulaCallContextAt(source, caret)
renderPointReference(anchor, focus, referenceMode)
```

They must share lexical rules for strings, doubled quote escapes, bracketed
names, identifiers, coordinates, commas, colons, operators, and parentheses.
Do not use regular expressions that split on the first colon or comma without
recognizing quoted/nested context.

Keep these helpers independent of Vue and cover them with table-driven tests.

### Grid Event Routing

At the start of grid pointer and keyboard handlers:

```javascript
if (this.formulaEditSession?.point || this.canPointFromFormulaEditor()) {
  if (this.handleFormulaPointEvent(event)) return;
}
```

Point handling must occur before normal card drag, grid selection, panning,
empty-cell creation, and menu handling.

Worker cards receive `draggable="false"` while a formula point gesture is
active. Pointer capture belongs to the grid viewport until commit or cancel.

### Focus And Blur

Replace unconditional inline-editor blur cancellation with a session-aware
rule:

- blur into a point-mode grid gesture preserves formula edit;
- blur into the help/completion panel preserves formula edit;
- blur elsewhere follows normal cancellation policy; and
- after point commit/cancel, restore input focus and exact caret position on
  the next Vue render tick.

Use an explicit focus-restoration target rather than document-wide timing
heuristics.

### Highlight Overlay

Render a point-selection rectangle in the grid's overlay layer using existing
grid geometry and row-height calculations. Do not mark each worker selected.
The overlay must work across occupied and empty cells and clip to the viewport.

Reference source highlighting may initially highlight the active preview span
as a whole. Per-reference syntax coloring for every formula token is deferred.

### Function Catalog

Move function metadata into a server module such as
`server/formula_functions.py`. The evaluator may retain its current execution
branches, but expose a testable set of implemented names and compare it with
catalog names.

Return catalog entries as read-only JSON. The frontend help component consumes
that catalog and never attempts to evaluate formulas.

### No Server Save During Pointing

Point movement, range resizing, reference-mode cycling, completion, and help
selection are client-local. Only the existing final formula commit reaches
`formula:set` or the worker-configuration save path.

---

## Acceptance Scenarios

1. In a formula at `D38`, type `=SUM(`, press ArrowLeft, hold Shift and press
   ArrowUp, then Enter. The editor contains a normalized two-cell range and
   remains open for `)`.
2. Type `=SUM(` and drag from `C36` through `C37`. Pointer-up inserts
   `C36:C37`, returns focus after the range, and does not move either worker.
3. Re-edit `=SUM(C36:C37)`, select `C36:C37`, enter point mode, and choose
   `D36:D37`. Only that source span changes.
4. Begin selecting a range, resize it several times, then Escape. The exact
   original source and selection return.
5. Begin point mode and press `$` repeatedly. Single references and both range
   endpoints follow the documented cycle.
6. Click an occupied worker card during point selection. Its coordinate is
   inserted; the card is not selected, opened, or dragged.
7. Drag across empty and occupied cells. One rectangular range is inserted.
8. Type `=SU`; completion offers `SUM` and `SUBSTITUTE`. Selecting `SUM`
   inserts `SUM(`.
9. With the caret in the first argument of `SUM`, signature help identifies
   the active argument and says that ranges are accepted.
10. In a nested formula, signature help follows the innermost function and
    changes argument after a top-level comma in that call.
11. Open the searchable library, inspect `TEXTJOIN`, insert it, and continue
    formula editing without losing the draft.
12. Open two browser windows. Point-mode previews remain local to the editing
    window; only the final saved formula is shared.

---

## Test Strategy

### Unit Tests

- valid and invalid reference insertion contexts;
- strings containing commas, colons, parentheses, and escaped quotes;
- bracketed names and function-name prefixes;
- coordinate/range replacement span detection;
- anchor/focus normalization in every drag direction;
- absolute-reference cycling for cells and ranges;
- preview update and exact cancellation restoration;
- nested function and active-argument detection;
- autocomplete filtering and insertion text; and
- evaluator/catalog name parity.

### Component Tests

- WorkerCard begins and renders a parent-owned formula session;
- compact prefix is excluded from formula offsets;
- empty-cell shortcut uses the same point state;
- editor blur is suppressed for grid pointing and help interaction;
- reference overlay does not mutate normal selection;
- card drag/menu/resize behavior is suppressed only during point gestures;
- help panel focus and Escape hierarchy; and
- config modal receives assistance without point selection.

### Browser Tests

- keyboard single reference and Shift+Arrow range;
- mouse click and four-direction mouse range sweep;
- viewport auto-pan during selection;
- Enter/Escape two-level behavior;
- re-edit and replace an existing range;
- absolute-reference cycle;
- occupied/empty mixed range without accidental worker movement;
- function completion, signature help, nested calls, and full library;
- exact source persistence after save/re-edit; and
- two-window locality before commit and synchronization after commit.

---

## Prioritized Decision Issues

### P0

1. **Modal scope.** Recommendation: point mode applies to inline worksheet
   editors and the empty-cell shortcut; the configuration modal receives
   function assistance only in v1 because it blocks grid interaction.
2. **Mouse commit.** Recommendation: a click or drag commits its reference on
   pointer-up, while keyboard pointing requires Enter or Tab.
3. **Arrow ambiguity.** Recommendation: arrows enter point mode only at a valid
   expression position; otherwise they retain ordinary caret behavior.
4. **Reference identity.** Recommendation: insert absolute grid coordinates as
   relative A1 text initially, with `$`/F4 cycling reference mode.
5. **Empty/self references.** Recommendation: allow selection and leave errors
   to the authoritative server evaluator.

### P1

1. Whether the full function library should remain a popover or become a
   dockable worksheet panel after v1 usage is understood.
2. Whether mouse click should leave point mode active for immediate adjustment
   instead of committing on pointer-up.
3. Whether later releases should color every reference independently in source
   and on the grid.

---

## Tranched Build Plan

Each tranche ends with focused tests, a commit, and a Bullpen ticket status
update.

### Tranche 1 — Function Catalog And Assistance

- Add the authoritative server function catalog and parity tests.
- Deliver it through a read-only application endpoint/bootstrap field.
- Implement function completion, signature/argument context, and searchable
  help panel.
- Integrate assistance with inline, shortcut, and modal formula inputs.

Checkpoint: commit assistance with catalog coverage for every evaluator
function and update the ticket with completion/signature/library test status.

### Tranche 2 — Unified Formula Edit Session

- Move worksheet formula draft/caret ownership to `BullpenTab`.
- Adapt regular, compact, and empty-cell editors to the shared session.
- Separate compact `name/unit:` prefix from formula source offsets.
- Implement lexical reference-context and replacement-span helpers.
- Preserve existing formula entry, commit, cancel, and re-edit behavior.

Checkpoint: commit the shared session with exact round-trip coverage for
numbers, ranges, and punctuation-heavy strings.

### Tranche 3 — Keyboard Point Mode

- Implement the point-mode state machine and preview rendering.
- Add arrow entry, arrow movement, Shift+Arrow range extension, viewport
  visibility, Enter/Tab commit, two-level Escape, and operator commit.
- Add `$`/F4 reference-mode cycling.
- Render point selection independently from normal grid selection.

Checkpoint: commit keyboard point mode with single-cell, range, replacement,
cancel, boundary, and absolute-reference browser tests.

### Tranche 4 — Pointer Point Mode

- Route capture-phase grid pointer events to point mode.
- Implement cell click, rectangular sweep, pointer capture/cancel, and edge
  auto-pan.
- Suppress worker drag, card actions, menus, connection handles, resizing, and
  ordinary selection during the gesture.
- Restore editor focus and caret reliably on pointer-up.

Checkpoint: commit pointer pointing with occupied/empty, four-direction sweep,
drag-suppression, and focus-restoration browser tests.

### Tranche 5 — Accessibility And End-To-End Reconciliation

- Add live announcements, listbox/combobox semantics, help descriptions, and
  non-color-only reference feedback.
- Run nested-help, keyboard-only, mouse-only, re-edit, and two-window scenarios.
- Reconcile `value-cell-formulas.md` with the delivered point-mode behavior.
- Document modal scope and deferred P1 assistance enhancements.

Checkpoint: commit the completed feature and update the implementation ticket
with the tranche/commit/test matrix.
