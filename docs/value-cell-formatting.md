# Value Cell Classification and Formatting

Status: Proposed specification  
Date: 2026-07-13  
Scope: Value worker entry, type preservation, display formatting, lifecycle,
MCP, history, triggers, migration, and browser verification

## Executive Summary

Bullpen Value cells need predictable number formatting, especially optional
thousands grouping and decimal-place control. The first implementation exposed
a deeper ambiguity: Bullpen has both a declared Type and a display Format, but
its Auto and General choices are not meaningfully distinct, some format choices
are inert, and type inference can run during operations that are not value
entry at all.

The solution is not to reproduce Excel's implicit cell engine. That would turn
every copy, import, paste, transfer, reload, and MCP call into another special
case in an expanding heuristic.

This specification adopts one small boundary:

> Infer type only when Bullpen genuinely receives untyped text. Otherwise honor
> an explicit type or preserve the type already stored in a Bullpen snapshot.

The resulting model is deliberately modest:

- **Type Auto** remains as an entry convenience.
- **Format Auto** is removed; **General** is the default display format.
- UI text entered under Type Auto uses one strict plain-number grammar.
- MCP JSON numbers are numbers and MCP JSON strings are strings under Auto.
- Explicit Type Number or String overrides inference.
- Copy, Paste Worker, Duplicate, Import Workers, Team load, Transfer, save/load,
  and restore preserve classified snapshots rather than re-infer them.
- Worksheet text paste is raw input and offers Infer Plain Numbers or Preserve
  as Text.
- Format and Unit never classify a value.
- General remains simple and ungrouped. Number and Currency own grouping and
  decimal-place controls.
- Browser display uses the browser locale. Server/MCP formatted text remains a
  documented deterministic `en-US` representation.
- Rounding is made consistent, but Bullpen does not add a workspace locale
  subsystem, ISO currency engine, arbitrary-precision value representation,
  scientific-width renderer, or additional Excel format categories in this
  work.

A broader lifecycle survey found several real leaks unrelated to numeric
grammar: normalization can reclassify Values during unrelated saves and reads;
format-only modal saves can resend stale values; Duplicate and Team operations
can copy history; bulk configure can bypass Value write behavior; and history
row deletion can overwrite newer history. This specification closes those
leaks with small structural rules rather than a larger type system.

## 1. Problem Statement

The current implementation has these user-visible or architectural problems:

- Format Auto and General both fall through to `String(value)`.
- The label **General (as entered)** is inaccurate because numeric entry has
  already discarded lexical details such as trailing zeros.
- Text left and Text right are offered but Value cards are always right-aligned.
- Number and Currency formatting differs between browser and server rounding.
- Browser separators are locale-aware while MCP/server separators are
  implicitly `en-US`, without saying so.
- Invalid explicit Number state can be normalized to zero in some paths.
- Layout normalization re-runs Auto inference. A restart, scheduler save, task
  queue update, service preview, MCP read, transfer, or unrelated worker save
  can therefore reinterpret a Value.
- Worker configuration sends a broad form snapshot. A user changing only
  Format can resend and overwrite a Value changed meanwhile by MCP.
- Format-only saves currently append Value history.
- `worker:configure_many` does not implement the history and trigger behavior
  of single Value writes.
- Copy/Paste, Duplicate, Transfer, Import, Team load, and workspace restore do
  not have an explicit shared rule for preserving versus reclassifying Value
  state.
- Disabling Save History clears history during normalization rather than simply
  stopping future recording.
- History deletion sends a replacement history array from the browser, which
  can erase an entry appended concurrently by MCP.

Excel remains a useful expectation reference for the visible distinction
between General and Number, but it is not the classification contract. Bullpen
intentionally avoids Excel conversions such as dates, currency-decorated
input, and silent removal of identifier zeros.

## 2. Goals

- Keep ordinary Value entry convenient: typing `13` under Auto produces a
  numeric Value.
- Preserve identifiers such as `00123` as text.
- Make General, Number, Currency, Text left, and Text right distinct and
  truthful.
- Keep grouping and decimal-place controls working for Number and Currency.
- Apply one explicit input rule at all raw-entry boundaries.
- Preserve already-classified Bullpen snapshots through structural lifecycle
  operations.
- Prevent reads, reloads, and unrelated layout writes from reclassifying Values.
- Make invalid explicit Number writes fail atomically rather than become zero.
- Keep history and value-change triggers correct and unsurprising.
- Preserve backward compatibility for existing Number/Currency display.
- Build a meaningful generated suite with thousands of assertions, including
  batched verification in real browsers.

## 3. Non-Goals

- Reproduce Excel's complete General heuristic.
- Automatically recognize dates, times, percentages, fractions, currency
  symbols, or localized thousands separators during entry.
- Add Percentage, Scientific, Accounting, Date, Time, Fraction, Special, or
  custom Excel format codes.
- Add arbitrary-precision arithmetic or a new decimal storage type.
- Add stable Value UUIDs, revision counters, an event journal, or a general
  optimistic-concurrency subsystem.
- Add a workspace number-locale setting.
- Add locale-aware ISO currency placement. Currency retains the existing custom
  symbol-prefix model in this tranche.
- Make General dynamically switch notation according to card width.
- Perform unit conversion.
- Turn Bullpen into a formula spreadsheet.

These may be proposed separately if concrete use cases justify them. They are
not prerequisites for honest, useful number formatting.

## 4. Terminology and Stored Model

### 4.1 Declared Type

`value_type` is the persistent entry policy:

```text
auto | number | string
```

- Auto uses the rules for the input source described below.
- Number requires a supported plain number.
- String stores text.

### 4.2 Resolved Type

`resolved_value_type` describes the stored value:

```text
number | string | null
```

An Auto cell may resolve differently after each genuine new entry. Once a
write succeeds, the resolved type is stored and remains authoritative until
another genuine value write occurs.

### 4.3 Display Format

`format.kind` controls presentation only:

```text
general | number | currency | string-left | string-right
```

Format never changes `value`, `value_type`, or `resolved_value_type`.

### 4.4 Unit

Unit is independent metadata. It may be appended to display text but is never
part of numeric parsing. `13` with Unit `kg` is numeric; raw text `13 kg` is not.

## 5. Input Classification Contract

Classification depends on both declared Type and input source. This is a small,
explicit protocol rather than an attempt to infer user intent everywhere.

### 5.1 Raw UI text under Type Auto

Initial typing, inline replacement, modal value entry, and worksheet cells in
Infer Plain Numbers mode are untyped text. Auto recognizes only this grammar:

```text
^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$
```

Accepted as Number:

```text
0
13
-13
+13
0.5
13.5
```

Preserved as String:

```text
00123
.5
13.
1e5
1,234
$13
13%
2/2
1-2
NaN
Infinity
```

Leading and trailing surrounding whitespace is trimmed by the entry control.
Whitespace inside the token is not numeric.

This grammar intentionally matches Bullpen's existing safe plain-number
concept. Expanding it requires an explicit future proposal, not another hidden
heuristic exception.

### 5.2 Precision safety

Auto text is numeric only when it contains at most 15 significant decimal
digits. Longer numeric-looking input is stored as String. Explicit Number
rejects it with a precision error.

This boundary keeps supported numeric Values inside the practical precision
shared by Python float/JSON/JavaScript display. It is a safety limit, not Excel
emulation.

Examples:

```text
123456789012345  -> Number
1234567890123456 -> String under Auto; rejected under Number
```

### 5.3 Explicit Type Number

Number applies the same grammar and precision boundary to UI text and MCP JSON
strings. JSON numbers are accepted when finite and within supported precision.

Invalid input rejects the entire operation. It never becomes zero.

### 5.4 Explicit Type String

String stores textual content. An MCP JSON number is converted to its stable
JSON textual representation. No numeric inference occurs.

### 5.5 MCP under Type Auto

MCP already has typed JSON, so transport type is authoritative:

| MCP `value` | Auto result |
|---|---|
| JSON number | Number, subject to finite/precision validation |
| JSON string | String, even when it contains `"42"` |
| JSON null | Null |

An MCP caller that intends a numeric conversion should send a JSON number or
explicitly set `value_type: number`. Bullpen does not reinterpret JSON strings
as numbers under Auto.

This differs from UI Auto because an HTML text input has no native numeric
type information. The difference is based on information actually available,
not on history or guesswork.

### 5.6 Empty and null

- Empty UI text under Auto is an empty String.
- MCP JSON null under Auto is Null.
- Number rejects empty and null.
- String converts null according to the existing empty-string convention.

Null and empty String remain distinct.

## 6. Classification Boundaries

The server classifies only when raw or explicitly retyped value input is
submitted:

- manual Value creation;
- inline or modal value edit;
- declared Type change involving the current value;
- MCP `set_value`;
- increment/decrement;
- worksheet text paste in Infer Plain Numbers mode;
- one-time migration of legacy state missing valid resolved metadata.

The server does not classify during:

- ordinary layout load or save;
- browser serialization;
- MCP list/get;
- scheduler ticks;
- task queue updates or worker execution;
- service preview or template interpolation;
- format, unit-only, name, or position changes;
- Copy/Paste Worker, Duplicate, current-schema Import, Team load, or Transfer;
- workspace backup restore with current-schema state.

### 6.1 Split normalization responsibilities

The implementation needs three explicit functions or equivalent boundaries:

- `classify_value_input(...)`: creates new typed state from genuine input.
- `validate_value_snapshot(...)`: validates stored or transported classified
  state without changing its type.
- `migrate_legacy_value(...)`: repairs missing legacy metadata once and reports
  what it did.

General layout normalization and serialization call snapshot validation, never
classification. Read paths are pure. Saving unrelated worker runtime state
cannot alter Value state.

## 7. Display Contract

### 7.1 General

General is the default format.

- Number: display the stored JavaScript number without grouping or padded
  fractional zeros.
- String: display stored text.
- Null/empty: use the existing empty-state behavior.
- Number aligns right.
- String aligns left.

The UI label is **General**, not **General (as entered)**. General does not
promise preservation of lexical trailing zeros.

General does not add Excel-like width-dependent scientific notation in this
work. The full display remains available in the card title when visual overflow
is truncated.

### 7.2 Number

Number exposes:

- Decimal places: Auto or fixed 0 through 10.
- Use thousands separator: on/off.

Auto displays up to ten fractional digits without padding insignificant zeros.
Fixed places round and pad to the selected count.

Newly selected Number defaults to grouping on and Auto decimal places.
Existing Number formats missing new fields retain grouping on and two fixed
decimal places for backward compatibility.

### 7.3 Currency

Currency retains the Number controls and the existing custom Symbol field. The
symbol is prefixed to the formatted number.

This is intentionally not a complete international currency engine. ISO codes,
locale-dependent symbol placement, accounting alignment, and currency-specific
minor-unit defaults are deferred.

### 7.4 Text left and Text right

Both display the value's plain text and force the requested alignment. They do
not change the resolved type.

### 7.5 Numeric formats applied to String

Number and Currency do not coerce String values. A String displays as text
without numeric decoration. The UI may explain that numeric formatting will
take effect when the cell contains a Number.

### 7.6 Rounding and locale

Fixed-place server formatting uses decimal arithmetic constructed from the
stable string form of the stored number and round-half-away-from-zero. Browser
formatting must match the same rounding results.

Required examples at two places:

```text
1.005  -> 1.01
2.675  -> 2.68
-1.005 -> -1.01
```

Browser Number/Currency uses the browser locale through `Intl.NumberFormat` or
`toLocaleString`.

Server/MCP `formatted_value` is deterministic `en-US`. MCP also returns:

```json
{"formatted_locale": "en-US"}
```

Raw MCP `value` remains the automation contract. The intentional difference in
separator locale is explicit rather than pretending the server knows the
viewer's browser locale.

## 8. Value-Write Transaction

Every genuine value write follows one server-authoritative transaction:

1. Load the current Value worker and capture old typed state.
2. Determine the effective declared Type. Omitted MCP `value_type` preserves
   the existing declaration; supplied `value_type` changes it persistently.
3. Classify or validate the submitted value according to input source and Type.
4. Normalize a separately supplied Unit without using it for classification.
5. Validate the complete proposed state.
6. On failure, change nothing.
7. Persist value, declared Type, resolved type, and optional Unit atomically.
8. Append one history entry when Save History is enabled.
9. Update `updated_at` once.
10. Save layout and emit one layout update.
11. Emit one value-change event.
12. Return the complete resulting state.

Failed writes do not change value, type, Unit, history, timestamp, or triggers.

Accepted no-op writes remain writes. They append history when enabled and emit
`changed: false`; existing `value_trigger_fire_on_noop` controls whether a
watcher reacts.

A declared Type change is a value write because it can change storage and
resolved type. Format, Unit-only, name, position, Save History, and history
maintenance are metadata operations, not value writes.

## 9. Lifecycle Contract

The broader lifecycle survey produces four operation classes.

### 9.1 Live value entry

These operations classify/validate new input, append history, update the
timestamp, and emit a value-change event:

- manual creation with an entered value;
- inline or modal overwrite;
- MCP `set_value`;
- increment/decrement;
- explicit declared Type change.

Manual creation currently fires value-change watchers and retains that
behavior. This is a deliberate live entry, not package bootstrap.

### 9.2 Structural creation from a classified snapshot

These operations preserve typed state, create a new local cell history
baseline, and do not emit value-change events:

- Paste Worker;
- Duplicate Worker or group;
- current-schema Import Workers;
- Team load;
- cross-workspace copy.

They validate snapshot coherence but never run Auto.

### 9.3 Identity relocation or restore

These preserve typed state and existing history and do not emit value-change
events:

- moving a worker within the grid;
- cross-workspace move;
- current-schema workspace backup restore.

### 9.4 Raw bulk bootstrap

Worksheet/tabular text paste classifies raw cells according to the selected
paste mode, creates local baseline history entries, emits one layout update,
and does not fire a storm of initial value-change events.

### 9.5 Operation matrix

| Operation | Classification | History | Value trigger |
|---|---|---|---|
| Manual create | Raw-entry rules | Initial entry | Yes |
| Manual overwrite | Raw-entry rules | Append | Yes |
| MCP set | JSON/explicit-Type rules | Append | Yes |
| Increment/decrement | Numeric validation | Append | Yes |
| Format or Unit-only edit | None | Unchanged | No |
| Name or grid move | None | Unchanged | No |
| Copy/Paste Worker | Preserve snapshot | New baseline | No |
| Duplicate Worker/group | Preserve snapshot | New baseline | No |
| Import current package | Preserve snapshot | New baseline | No |
| Import legacy missing type metadata | One safe migration | New baseline | No |
| Worksheet paste | Selected raw-text mode | New baseline | No |
| Team load | Preserve template snapshot | New baseline | No |
| Cross-workspace copy | Preserve snapshot | New baseline | No |
| Cross-workspace move | Preserve snapshot | Preserve | No |
| Workspace restore | Preserve/migrate archive | Preserve | No |
| Delete Value | None | Deleted with cell | No |
| History clear/delete | None | Explicit maintenance | No |
| Reload/read/serialize | None | Unchanged | No |

## 10. Detailed Structural Operations

### 10.1 Import Workers

Current-schema packages carry `value`, `value_type`, and
`resolved_value_type`. Import validates that:

- resolved Number has a finite supported JSON number;
- resolved String has text;
- resolved Null has null;
- declared Type is supported;
- format and Unit are structurally valid.

It preserves the resolved type even when an Auto String contains `"42"`.

Legacy packages missing resolved metadata use a conservative migration:

- JSON number becomes Number;
- JSON string remains String;
- JSON null becomes Null;
- explicit Number with incompatible text produces a preview error rather than
  silent coercion.

Import preview reports the resulting type. Imported source history and
timestamps are stripped; the local cell receives one baseline entry when Save
History is enabled. Import is atomic and fires no Value triggers.

### 10.2 Copy/Paste Worker and Duplicate

The classified snapshot includes value, declared Type, resolved type, Unit,
Format, and Save History. Paste and Duplicate:

- preserve those fields;
- validate but do not infer;
- assign normal new-worker name/position state;
- discard source history and timestamp;
- create one new local baseline history entry;
- emit no Value trigger.

Replacement Paste is delete-plus-create, not an old-target/new-target value
write. Group Paste and Duplicate Group preflight every member and commit all or
none.

### 10.3 Worksheet paste

The browser sends every clipboard cell as raw text. It does not pre-convert
selected cells into JavaScript numbers.

The user-facing choices are:

- **Infer Plain Numbers**: apply the strict UI Auto grammar to each cell.
- **Preserve as Text**: create Type String cells.

Ordinary worksheet Paste may default to Infer Plain Numbers, with Paste as Text
available in the empty-cell menu and paste preview. The rectangular operation
validates all coordinates and commits all cells or none.

### 10.4 Cross-workspace Transfer

- Copy creates a new destination snapshot with no source history and one local
  baseline.
- Move preserves the Value snapshot, history, and timestamp while changing its
  workspace and possibly its name/position.
- Destination locale can change visible browser separators but never type.
- Neither operation fires Value triggers in source or destination.

Group transfer currently applies members sequentially and can partially
complete. That is a general worker-transfer atomicity issue. The Value work
must either preflight and commit the whole requested group or return an
explicit partial-result contract; silent partial success is unacceptable.

### 10.5 Team save/load

Teams are templates, not backups.

- Team save preserves the current Value snapshot, Unit, Format, and Save
  History setting but strips Value history and timestamps.
- Team load validates the stored snapshot, creates new local baseline history,
  and fires no Value triggers.
- Legacy Team snapshots use the same conservative migration as legacy import.

### 10.6 Workspace backup restore

A workspace archive is a backup, not a template. Current-schema restore
preserves Value state, history, timestamps, and formats exactly. Legacy state
is migrated once during staged import and the migration is reported.

Restore fires no Value triggers. Archive replacement should be staged and
validated before replacing the live `.bullpen` directory so a failed repair
does not destroy the current workspace.

### 10.7 Rename, move, and delete

Rename and grid movement do not classify or emit value-change events. They may
change which loose name or absolute-coordinate watchers match future writes;
that existing binding behavior remains explicit.

Deleting a Value emits no value-change event. Name watchers remain configured;
coordinate watchers observe a future Value placed at that coordinate.

## 11. History Lifecycle

### 11.1 Save History toggle

Turning Save History off stops future appends but does not erase existing
history. Turning it back on resumes appends. Clearing history is a separate,
explicit action.

### 11.2 History entries are snapshots

Existing history entry `resolved_value_type` is preserved on load. History
normalization validates entry shape but does not re-run current Auto inference.

### 11.3 Delete and clear operations

The browser must not replace the whole history array to delete one row. A stale
array can erase entries appended by MCP after the history dialog opened.

Add dedicated server-backed operations:

- delete the selected row by its snapshot fingerprint and occurrence;
- clear the current history intentionally.

Both run under the write lock against current server state. They do not alter
the current Value timestamp or fire Value triggers.

### 11.4 Export

History CSV continues to export raw values and declared/resolved types. Display
formatting is not baked into raw history export.

## 12. Configuration and Concurrency Boundaries

### 12.1 Dirty-field saves

The Value configuration modal submits only fields changed by the user. Changing
Format must not resend `value`; changing Unit only must not resend `value`.

This prevents a modal opened before an MCP write from overwriting the newer
Value when the user later changes only formatting.

Inline value editing remains an intentional last-writer-wins value write in
this tranche. A broader revision/CAS system may be proposed separately if real
multi-client conflicts justify it.

### 12.2 Bulk configure

`worker:configure_many` rejects `value`, `value_type`, and raw `history` fields.
Bulk metadata changes such as Format or Unit may be supported, but they do not
append history, update Value timestamps, or fire triggers.

Bulk value assignment requires a dedicated future operation with explicit
atomic and trigger semantics.

### 12.3 Type-only changes

Changing declared Type intentionally reprocesses the current value under the
new explicit policy and is a value write. It appends history and emits a trigger
event even if the raw display remains equal; watcher no-op settings apply.

## 13. Lifecycle Leak Survey

The code survey covered these surfaces:

- `worker:add`, `worker:configure`, and `worker:configure_many`;
- `value:set` and `value:increment` used by MCP;
- Copy/Paste Worker and worker groups;
- Duplicate and Duplicate Group;
- Bento preview/import/export;
- cross-workspace copy/move;
- Team save/load;
- workspace/all-workspace archive restore;
- startup reconciliation and ordinary state load;
- scheduler and worker runtime layout saves;
- service preview and Value template reads;
- MCP list/get serialization;
- move, rename, remove, and replacement paste;
- history append, delete, clear, toggle, and CSV export;
- value-change trigger event construction and comparison.

### 13.1 Leaks that this work must close

1. **Load-time inference:** `normalize_worker_slot()` currently calls
   `normalize_value_payload()` for every Value.
2. **Unrelated-save persistence:** event, worker, scheduler, transfer, archive,
   and service paths normalize entire layouts; a task/runtime save can persist
   a reclassified Value.
3. **Read-time reinterpretation:** app state and MCP reads serialize normalized
   layouts and can present a type different from the stored snapshot.
4. **Trigger reconstruction:** value-change event construction re-normalizes
   old and new values instead of consuming the already accepted typed states.
5. **Format history pollution:** single-worker configure appends history when
   Format changes.
6. **Broad modal overwrite:** modal Save includes the current form Value even
   for metadata-only edits.
7. **Bulk-config bypass:** `configure_many` can admit Value-specific fields but
   does not perform corresponding history or trigger behavior.
8. **Copy inconsistency:** browser Paste omits history, while server Duplicate
   and transfer helpers can preserve it.
9. **Team history cloning:** Team save/load currently copies Value history even
   though a Team is a template.
10. **History toggle deletion:** normalization empties history when Save History
    is false.
11. **Stale history replacement:** row deletion sends an entire client-side
    history array.
12. **Browser worksheet pre-coercion:** worksheet payload construction must not
    mix raw strings and client-converted numbers before server classification.
13. **Partial group transfer:** sequential cross-workspace transfer can leave a
    partially copied/moved group.
14. **Destructive restore window:** workspace restore deletes live state before
    replacement validation/reconciliation has fully succeeded.

### 13.2 Surveyed behaviors that are not leaks

- Accepted no-op writes intentionally create events.
- Rename and coordinate movement intentionally change future loose watcher
  matching without firing a Value event.
- Deletion intentionally does not masquerade as a value change.
- Browser and MCP separator locales may differ because MCP declares its fixed
  `en-US` formatted locale and also returns raw value.
- Inline edit remains last-writer-wins because it is an intentional value
  write, not a metadata-only save.

### 13.3 Broader concerns recorded but not expanded here

Cross-file transfer transactions and archive directory replacement affect all
worker types. This spec states the required Value outcome but does not invent a
general transaction journal. Those concerns may become focused platform
tickets if the existing preflight/staging changes cannot address them simply.

## 14. Migration and Compatibility

Migration is explicit, versioned, and idempotent.

- `format.kind: auto` becomes `general`.
- Existing Number/Currency without `places` retains fixed two decimals.
- Existing Number/Currency without `grouping` retains grouping on.
- Existing valid `resolved_value_type` is preserved.
- Existing JSON numbers missing resolved metadata become Number.
- Existing JSON strings missing resolved metadata remain String; migration does
  not parse numeric-looking strings.
- Invalid explicit Number state is reported for repair and never becomes zero.
- Existing history entries preserve valid stored types.
- Existing Currency symbols remain custom symbols.
- Running migration twice produces no further change.

Ordinary load is not migration. Migration runs during a versioned startup step,
package preview/import, or explicit repair operation and reports what changed.

## 15. Test Strategy

Thousands of cases are appropriate for the small parser/formatter contract,
but thousands of browser startups are not. The suite uses a reviewed golden
corpus plus deterministic generated batches evaluated by Python and the real
browser implementation.

Target: at least **8,000 deterministic assertions** in the full Chromium run,
including at least **2,000 cases evaluated in real Chromium**. The target is a
floor, not a reason to generate redundant Cartesian noise.

### 15.1 Shared conformance corpus

Create:

```text
tests/fixtures/value_formatting/
  classification-golden.json
  formatting-golden.json
  lifecycle-snapshots/
  migration-layouts/
```

Golden cases include:

- every accepted and rejected lexical form;
- surrounding/internal whitespace;
- leading-zero identifiers;
- 14/15/16 significant-digit boundaries;
- JSON number/string/null under every declared Type;
- invalid explicit Number behavior;
- General, Number, Currency, Text left, and Text right;
- grouping on/off and Auto/fixed 0-10 places;
- rounding ties, signs, and negative zero;
- representative `en-US`, `de-DE`, and `fr-FR` browser display;
- legacy/current snapshot migration;
- all lifecycle operation classes.

Each case has a stable ID, input, expected result/error, and rationale.

### 15.2 Generated parser tests

Generate at least **2,500 assertions** across:

- UI raw text versus MCP typed JSON;
- Auto, Number, and String;
- sign, integer length, fractional length, and precision boundary;
- supported and decorated forms;
- old resolved type, proving it does not affect new Auto classification;
- Unit and Format variations, proving they do not affect classification.

### 15.3 Generated formatter tests

Generate at least **3,500 server assertions** across:

- positive, negative, zero, and negative zero;
- integer and fractional magnitudes;
- places Auto and 0-10;
- grouping on/off;
- Number and Currency symbols;
- tie and near-tie rounding cases;
- String values under numeric formats.

### 15.4 Real-browser conformance

Python Playwright loads the actual browser formatting module served by Bullpen
and evaluates at least **2,000 cases** in batches using `page.evaluate`.

Expected values come from reviewed golden data or independently verified server
rounding data; the browser test does not call the same function to generate its
oracle.

Browser assertions cover:

- formatted text;
- browser-locale separators;
- grouping and decimal padding;
- computed left/right alignment;
- raw editor value versus formatted card text;
- overflow title containing the full value;
- every visible configuration choice.

Chromium runs on each tranche. Firefox and WebKit run the golden corpus and a
representative generated subset nightly or before release.

### 15.5 Lifecycle integration tests

At least 100 focused assertions cover:

- manual create/overwrite;
- MCP JSON number/string transitions;
- explicit Type changes;
- no-op writes;
- increment;
- metadata-only dirty-field saves;
- Copy/Paste, Duplicate, Import, Team load, Transfer copy/move;
- worksheet Infer and Preserve modes;
- workspace restore and restart;
- history toggle/delete/clear with an intervening MCP write;
- name/move/delete watcher behavior;
- bulk-config rejection;
- group atomicity or explicit partial-result behavior.

Every structural operation asserts stored value, declared/resolved type,
history policy, timestamp policy, trigger count, and reload equality.

### 15.6 Regression invariants

- Reading or serializing a layout never changes any Value field.
- Saving unrelated worker/task/runtime state never changes any Value field.
- A valid classified snapshot survives 100 normalize/save/load cycles exactly.
- Format and Unit-only saves never append history or fire triggers.
- Failed Number writes leave serialized state unchanged.
- Snapshot operations never call the classifier.
- Raw-entry operations always call the classifier exactly once per cell.
- Browser worksheet paste sends only raw strings.
- A history delete cannot erase an entry appended after the dialog opened.

### 15.7 Diagnostics

Generated failures report case ID, input source, declared Type, expected and
actual resolved state, Format, locale, and browser version. DOM failures capture
Playwright trace and screenshot. Any discovered generated regression is added
to the golden corpus before closure.

## 16. Phased Implementation Plan

### Phase 0 — Characterization and conformance harness

- Extract classification and browser formatting into directly testable modules.
- Add the golden corpus and deterministic generators.
- Add the batched Chromium harness.
- Characterize current migration and lifecycle behavior, including expected
  failures for known leaks.

Exit: the suite can show current duplicate Auto/General behavior, rounding
disagreement, and reclassification leaks with named cases.

### Phase 1 — Small type and format contract

- Remove Format Auto from the UI and accept it as a General compatibility alias.
- Default new Values to Type Auto + General.
- Implement strict source-aware classification.
- Reject invalid Number instead of storing zero.
- Make Text left/right and General type alignment functional.
- Split input classification from snapshot validation and migration.
- Make load, serialization, scheduler, runtime, service, and MCP read paths
  snapshot-preserving.

Exit: inference happens only at documented input boundaries; restart and
unrelated saves cannot alter Values.

### Phase 2 — Lifecycle leak closure

- Make the modal submit dirty fields only.
- Prohibit bulk value/history writes through `configure_many`.
- Remove format-only history writes.
- Implement the lifecycle table for Paste, Duplicate, Import, worksheet paste,
  Team, Transfer, restore, move, rename, and delete.
- Strip or preserve history according to snapshot creation versus identity move.
- Make Save History non-destructive.
- Add dedicated history delete/clear operations.
- Stage workspace restore before replacement.
- Preflight group operations or expose explicit partial results.

Exit: every surveyed lifecycle surface has a test asserting classification,
history, timestamp, triggers, atomicity, and reload behavior.

### Phase 3 — Number/Currency parity and browser completion

- Use decimal server rounding that matches browser results.
- Keep browser-locale display and declare MCP `en-US` formatting.
- Complete Number/Currency grouping and decimal-place behavior.
- Complete DOM, accessibility, Chromium, and cross-browser golden coverage.
- Preserve legacy Number/Currency appearance.

Exit: basic formatting is reliable and the required browser/server suites pass.

## 17. Suggested Ticket Breakdown

1. **Value formatting: conformance corpus and Chromium batch harness**
2. **Value classification: separate raw input from stored snapshot validation**
3. **Value formats: replace Format Auto with functional General and text
   alignment**
4. **Value lifecycle: make copy/import/team/transfer/history behavior explicit**
5. **Value configuration: dirty-field saves and bulk-write guardrails**
6. **Value Number/Currency: consistent rounding and declared MCP locale**

Additional Excel formats, arbitrary precision, optimistic concurrency, and a
general transfer transaction system require separate evidence and proposals.

## 18. Final Acceptance Criteria

The work is complete when:

- Type inference occurs only for documented raw-entry sources.
- MCP JSON type is honored under Auto.
- Stored Bullpen snapshots are preserved through every structural lifecycle
  operation and ordinary load/save.
- Format and Unit never classify a Value.
- General, Number, Currency, Text left, and Text right are truthful and distinct.
- Grouping and Auto/fixed decimals work in the browser.
- Browser and server agree on rounding; MCP declares its separator locale.
- Invalid Number input never becomes zero or partially changes state.
- Metadata-only saves do not overwrite Values, append history, or fire triggers.
- Copy/import/template history behavior follows the lifecycle table.
- Save History is non-destructive and history maintenance cannot lose a newer
  append.
- All surveyed read, runtime, migration, copy, import, transfer, team, restore,
  and trigger paths have focused regression coverage.
- The full suite executes at least 8,000 deterministic assertions, including at
  least 2,000 real-Chromium cases and cross-browser golden coverage.

