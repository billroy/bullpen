# Conditional Value Triggers

## Summary

Conditional Value Triggers extend **On Value Change** workers with an optional
predicate over the value event's `new_value`. A reacting worker can continue to
fire on any matching Value write, or it can fire only when the new value
satisfies one simple comparison:

```text
any | contains | < | <= | == | > | >=
```

This feature is a filter on top of the existing value-change trigger described
in [Value Change Trigger](value-change-trigger.md). It does not create a new
activation type. The trigger still belongs to the reacting worker, not to the
Value worker.

Example:

```json
{
  "activation": "on_value_change",
  "value_trigger_scope": "name",
  "value_trigger_ref": "Open defects",
  "value_trigger_condition_operator": ">=",
  "value_trigger_condition_value": "5"
}
```

With this configuration, the worker fires only when a Value worker named
`Open defects` is written and its new stored value is greater than or equal to
`5`.

## Goals

- Add a comparison filter to existing `activation: "on_value_change"` workers.
- Preserve today's behavior by default: every accepted matching value write
  fires unless other trigger settings suppress it.
- Support numeric thresholds for numeric Value workers.
- Support equality, containment, and transparent alphabetic ordering for string
  Value workers.
- Support `contains` for both string and numeric Value workers by comparing
  against the event value's text form.
- Treat the configured comparison value as text at rest, then interpret it
  according to the operator and the changed Value worker's effective type at
  trigger time.
- Make conversion behavior visible in the UI before save and in diagnostics
  after save.
- Include the accepted condition configuration and condition evaluation result
  in synthetic ticket metadata.
- Avoid firing, updating cooldown, or creating tickets when the condition does
  not match.

## Non-Goals

- No compound boolean expressions.
- No comparisons against `old_value`, `changed`, value name, coordinate, units,
  or actor metadata in v1.
- No regex, starts-with, ends-with, or case-insensitive string modes.
- No arithmetic expressions such as `>= {A1} + 5`.
- No formula graph or recalculation semantics.
- No per-Value-worker trigger configuration.
- No new trigger activation. This is an option within `on_value_change`.

## Configuration Model

Add two fields to workers that support `activation: "on_value_change"`:

```json
{
  "value_trigger_condition_operator": "any",
  "value_trigger_condition_value": ""
}
```

Fields:

| Field | Type | Default | Notes |
|---|---|---:|---|
| `value_trigger_condition_operator` | string | `"any"` | One of `any`, `contains`, `<`, `<=`, `==`, `>`, `>=` |
| `value_trigger_condition_value` | string | `""` | Raw configured comparison text; ignored when operator is `any` |

`value_trigger_condition_value` is always persisted as a string. The server
must not pre-coerce it during save because the changed Value worker's
`resolved_value_type` may change between writes when its declared type is
`auto`.

Existing configs without these fields behave as:

```json
{
  "value_trigger_condition_operator": "any",
  "value_trigger_condition_value": ""
}
```

Unsupported worker types must drop these fields during normalization, following
the same rules as the existing `value_trigger_*` fields.

## UI Behavior

In the worker configuration modal, when an eligible worker has
`Input Trigger: On Value Change`:

- Show a comparison selector after the Value picker.
- Selector options are **Any change**, **Less than**, **Less than or equal**,
  **Equal to**, **Contains**, **Greater than**, and
  **Greater than or equal**.
- When **Any change** is selected, hide the comparison value input and save
  `value_trigger_condition_operator: "any"`.
- When any comparison operator is selected, show one comparison value input.
- The comparison value input is plain text, not a number-only field, because it
  may be evaluated against either numeric or string values at trigger time.
- Show helper text or a preview line based on the currently selected Value
  worker when possible:
  - numeric current value with a relational operator: `Comparison value will be parsed as a number.`
  - numeric current value with `contains`: `Contains compares against the value's text form.`
  - string current value: `Comparison value will be compared as text.`
  - any-value scope or missing target: `The comparison value is interpreted using the changed value and operator at run time.`
- If the current target is numeric and the configured comparison value cannot
  be parsed as a valid number for a relational operator, show a non-blocking
  warning before save.
- If the current target is string and the operator is `<`, `<=`, `>`, or `>=`,
  show a non-blocking warning that ordering is alphabetic, not numeric.
- Reopening the modal must round-trip the operator and comparison value exactly.

The UI may allow saving a condition that cannot currently be evaluated, because
the selected Value worker may be missing, the trigger may use **Any Value**, or
an `auto` value may later change type. Invalid-at-trigger-time conditions simply
do not match and should produce a debug/config warning.

## Trigger Semantics

Conditional filtering runs inside the existing value-change trigger pipeline.
An accepted value write fires a reacting worker only when all of these are true:

1. The event matches the worker's existing `value_trigger_scope` and
   `value_trigger_ref`.
2. The no-op setting allows the event:
   `value_trigger_fire_on_noop` is true or the normalized value changed.
3. The reacting worker is not paused and global automation is not paused.
4. The worker is not already in its cooldown window.
5. The condition operator is `any`, or the event's `new_value` satisfies the
   configured condition.

Condition failures are normal filtered events. They must not create synthetic
tickets, start workers, update `last_value_trigger_time`, or consume cooldown.

If condition evaluation fails because the comparison value cannot be coerced to
the event type, the condition does not match. The server should log a concise
debug warning with the reacting slot, operator, raw comparison text, value type,
and value event id.

## Type And Comparison Rules

The event's `new_value_type` controls coercion:

| `new_value_type` | Coercion of configured text | Supported operators |
|---|---|---|
| `number` | Strict plain-number parse after trimming for relational operators; raw text for `contains` | `contains`, `==`, `<`, `<=`, `>`, `>=` |
| `string` | Exact configured text as entered | `contains`, `==`, `<`, `<=`, `>`, `>=` |

Values with missing or unknown `new_value_type` do not match relational
conditions. They still match `any`.

### Numeric Values

When `new_value_type` is `number`, the configured comparison text is parsed
using the same plain-number grammar as Value worker numeric input for `==`,
`<`, `<=`, `>`, and `>=`:

- Trim leading and trailing whitespace before parsing.
- Accept integers and decimals such as `5`, `-2`, `0.75`, and `5.0`.
- Reject empty text.
- Reject `NaN`, `Infinity`, `-Infinity`, hexadecimal, binary, percentages,
  currency symbols, thousands separators, units, dates, versions, and paths.

Numeric comparisons use normal numeric ordering. `==` is exact numeric equality
after parsing, so `5`, `5.0`, and `05.00` compare equal if the parser accepts
them. `-0` and `0` compare equal.

If parsing fails, the condition evaluates to false.

Numeric `contains` is intentionally text containment, not numeric comparison.
The server converts `new_value` to Bullpen's canonical raw number text and tests
whether that text contains `value_trigger_condition_value` exactly. The
configured comparison text is not parsed as a number for `contains`.

Examples:

```text
123 contains "2"
5.25 contains ".2"
```

The canonical raw number text should use the same representation that Value
interpolation and MCP responses use for raw numeric values. It must not use
locale-specific thousands separators, currency formatting, or display-format
rounding.

### String Values

When `new_value_type` is `string`, the configured comparison text remains a
string. The server does not try to parse it as a number, date, currency, or
boolean.

String `==` uses exact string equality after Bullpen's normal single-line text
input normalization and condition-value trim-on-save. It is case-sensitive.
Leading and trailing spaces in the configured comparison value are not
significant in v1.

String `contains` uses exact, case-sensitive substring matching. An empty
comparison string matches every string value, because every string contains the
empty string. The UI should discourage empty `contains` values because they are
equivalent to `any` for string values and most numeric values, but the server
can keep the behavior simple and deterministic.

String ordering for `<`, `<=`, `>`, and `>=` is lexicographic by Unicode code
point. This keeps the behavior deterministic and easy to reproduce, but it
means:

```text
"10" < "2"
"Beta" < "alpha"
```

The UI should describe this as alphabetic/text ordering. Users who want numeric
ordering must store the Value worker as a number.

## Examples

| Value `new_value` | `new_value_type` | Operator | Configured value | Fires? | Reason |
|---|---|---|---|---:|---|
| `5` | `number` | `>=` | `5` | yes | `5 >= 5` |
| `4.9` | `number` | `>=` | `5` | no | `4.9 < 5` |
| `5` | `number` | `==` | `5.0` | yes | numeric equality |
| `5` | `number` | `>` | `5%` | no | threshold is not a valid number |
| `123` | `number` | `contains` | `2` | yes | canonical numeric text contains `2` |
| `5.25` | `number` | `contains` | `.2` | yes | canonical numeric text contains `.2` |
| `"5"` | `string` | `==` | `5` | yes | exact string equality |
| `"release/2026-06"` | `string` | `contains` | `2026` | yes | substring match |
| `"10"` | `string` | `<` | `2` | yes | text ordering |
| `"Beta"` | `string` | `<` | `alpha` | yes | uppercase code points sort before lowercase |
| `"release/2026-06"` | `string` | `==` | `release/2026-06` | yes | exact string equality |

## Synthetic Ticket Contract

When a condition passes and the existing value-change trigger creates a
synthetic ticket, add condition metadata to `value_trigger`:

```yaml
value_trigger:
  event_id: "..."
  scope: "name"
  configured_ref: "Open defects"
  value_name: "Open defects"
  value_coord: "B4"
  old_value: 4
  old_value_type: "number"
  new_value: 5
  new_value_type: "number"
  changed: true
  condition:
    operator: ">="
    configured_value: "5"
    coerced_value: 5
    coerced_value_type: "number"
    matched: true
```

For `operator: "any"`, the condition block should still be present:

```yaml
condition:
  operator: "any"
  configured_value: ""
  coerced_value: null
  coerced_value_type: null
  matched: true
```

For `contains`, `coerced_value` should be the configured comparison string used
for substring matching and `coerced_value_type` should be `"string"`, even when
the changed Value worker is numeric.

Filtered-out events do not create tickets, so their condition results are
visible only through logs or future diagnostics.

The ticket body should include a short line when the condition is not `any`:

```text
Condition: new value >= 5 (matched)
```

## Server Architecture

Add a server-side helper for condition evaluation near the existing
`_value_trigger_matches` logic:

```python
def _value_trigger_condition_matches(value_event, worker):
    ...
```

Return a structured result rather than only a boolean:

```python
{
    "matched": True,
    "operator": ">=",
    "configured_value": "5",
    "coerced_value": 5,
    "coerced_value_type": "number",
    "error": None,
}
```

The existing `_fire_value_change_triggers` flow should evaluate conditions
after scope/no-op/pause/cooldown checks and before `last_value_trigger_time` is
updated or `_create_value_trigger_task` is called.

Recommended order:

1. Build the accepted `value_event`.
2. Iterate reacting workers in slot order.
3. Skip workers that do not match scope.
4. Skip no-op events when the worker opts out.
5. Skip paused workers and global automation pause.
6. Skip workers in cooldown.
7. Evaluate the condition.
8. If matched, update `last_value_trigger_time`, persist layout, create the
   synthetic ticket, and queue/start the worker.

Condition evaluation must be server-side. Frontend checks are only previews.
MCP, UI, worker-configure, and future write paths must all use the same
condition logic.

## Validation And Persistence

Validation requirements:

- `value_trigger_condition_operator` must be one of `any`, `<`, `<=`, `==`,
  `>`, `>=`, `contains`.
- Missing or invalid operators normalize to `any` for legacy/imported data, but
  interactive save should reject invalid operators.
- `value_trigger_condition_value` must be a string after coercion and should
  observe the same maximum length as other short worker config strings.
- `value_trigger_condition_value` may be blank in storage, but relational
  operators with blank values will not match numeric values. Blank `contains`
  values follow ordinary substring rules and should match string values plus
  numeric values with a known canonical text representation.
- When the operator is `any`, normalize the stored comparison value to `""`.
- Copy/paste, duplicate, team save/load, transfer, and Bento package import
  should preserve the condition fields for eligible workers.
- Runtime state such as `last_value_trigger_time` remains server-owned and is
  unaffected by filtered-out events.

## Security And Safety

This feature can reduce automation noise, but it does not reduce the security
impact of Value writes. A Value write that satisfies a condition can still
start AI, Shell, or Notification workers.

Safety requirements:

- MCP docs should continue to warn that `set_value`, `increment_value`, and
  `decrement_value` can trigger automation.
- The worker config modal should make the condition visible wherever
  `on_value_change` is visible.
- Imported workers with conditional value triggers are still effectful
  automation and should follow the same import review policy as unconditional
  value-change triggers.
- String relational operators should be visibly described as text ordering so
  users do not mistake `"10" < "2"` for numeric behavior.

## Testing Plan

Backend tests:

- Missing condition fields preserve current value-change behavior.
- `operator: "any"` fires exactly as today.
- Numeric `>`, `>=`, `==`, `<`, and `<=` match and reject expected values.
- Numeric conditions reject invalid thresholds such as `""`, `5%`, `$5`,
  `1,000`, `NaN`, and `Infinity`.
- Numeric equality treats `5` and `5.0` as equal.
- Numeric `contains` matches against canonical raw number text and does not
  parse the configured comparison value as a number.
- String equality is exact and case-sensitive.
- String `contains` is exact and case-sensitive.
- String ordering is deterministic and covered for `"10" < "2"` and
  `"Beta" < "alpha"`.
- An `auto` Value worker can fire numerically on one write and compare as a
  string on a later write after its resolved type changes.
- Filtered-out events do not create tickets, update cooldown, or start workers.
- Passing conditions add the condition block to `value_trigger` metadata.
- Condition fields are removed from unsupported worker types.
- Copy/paste, duplicate, team save/load, transfer, and package import preserve
  condition fields for eligible workers.

Frontend tests:

- The comparison selector appears only for `On Value Change`.
- `Any change` hides the comparison value input.
- Relational operators show the text comparison value input.
- `Contains` shows the text comparison value input.
- Reopen round-trips operator and comparison value.
- Numeric selected values show numeric parsing guidance.
- Numeric selected values with `contains` show text-containment guidance rather
  than numeric parsing guidance.
- String selected values with relational operators show text-ordering guidance.
- Any-value scope explains that type is decided at trigger time.
- Any-value scope with `contains` explains that containment uses the changed
  value's text form at trigger time.

End-to-end tests:

- Configure a Notification worker for a named numeric Value worker with
  `>= 5`; verify writes `4` and `4.9` do not create tickets, and write `5`
  creates one synthetic ticket.
- Configure a Shell worker for an `auto` Value worker with `== 5`; verify
  numeric `5` fires and string `05` does not fire unless the condition is
  changed to string equality.
- Configure a Notification worker for a string Value worker with `< 2`; verify
  writing `10` fires and the synthetic ticket records string condition
  metadata.
- Configure a Notification worker with `contains 2026`; verify both a string
  value `release/2026-06` and a numeric value `2026.06` can fire when their
  canonical text contains `2026`.
- Verify two connected browsers see only the synthetic tickets for passing
  conditions.

## Open Issues

1. **String ordering UX.** Text ordering is deterministic but surprising for
   numbers stored as strings. The first implementation should decide how
   prominent the warning needs to be in the modal, especially for **Any Value**
   triggers where the runtime value may be a string. The exact ordering rule
   should be covered in implementation tests and visible enough that users do
   not expect numeric comparison from string values.
2. **Whitespace preservation.** V1 trims `value_trigger_condition_value` on
   save, so string equality is exact after trim. If future workflows need
   leading/trailing whitespace to be significant, the UI and validation path
   must preserve it deliberately and add tests for that mode.
3. **Diagnostics for filtered events.** Filtered events produce no ticket.
   Users may need a lightweight debug surface to explain why a condition did
   not fire, especially for **Any Value** triggers where the value type can
   change. Possible v1 surfaces include debug logs only, a config-modal "last
   filtered event" detail, worker focus/output metadata, or a bounded in-memory
   diagnostics list. Diagnostics should include condition operator, configured
   comparison value, runtime value type, and reason for non-match where
   available.
4. **Future string operators.** Equality, containment, and lexicographic
   ordering cover the requested selector, but common workflows may want
   `starts with`, regex, or case-insensitive equality. Those should be separate
   features rather than quietly added to v1.
5. **Dynamic thresholds.** Comparing against a fixed text field is simple.
   Comparing against another Value worker, such as `new_value >= {threshold}`,
   would be useful but needs cycle, lookup, and ticket-metadata design.

## Implementation Plan

### Readiness Assessment

This feature is ready for implementation planning and close to ready for
coding. The existing `on_value_change` implementation already has the right
server-side observer shape:

- `_value_trigger_matches` handles scope matching,
- `_fire_value_change_triggers` is the single trigger firing point,
- `_create_value_trigger_task` centralizes synthetic ticket metadata,
- `WorkerConfigModal.js` already owns all value-trigger configuration UI,
- `tests/test_events.py` and `tests/test_frontend_value_change_trigger.py`
  already cover the current value-trigger behavior.

The work should be a narrow extension rather than a redesign.

### Pre-Coding Decisions

Resolve these before implementation starts:

1. **Whitespace policy for condition values.** V1 trims
   `value_trigger_condition_value` on save for consistency with existing short
   config fields, so string equality is exact after trim.
2. **Filtered-event diagnostics scope.** Implement debug logging in v1, not a
   user-facing diagnostics panel. The log should include slot, operator,
   configured value, runtime value type, event id, and reason. A richer UI can
   follow later.
3. **Canonical numeric text helper.** Reuse or extract the behavior from
   `server/templates.py::raw_value_text` for numeric `contains`. If a new
   helper is introduced, both templates and condition evaluation should call
   it so Value interpolation, MCP payloads, and numeric `contains` stay aligned.

### Phase 1: Schema And Normalization

Files:

- `server/validation.py`
- `server/worker_types.py`
- `static/components/WorkerConfigModal.js`
- `tests/test_validation.py`
- `tests/test_worker_types.py`
- `tests/test_frontend_value_change_trigger.py`

Tasks:

- Add `VALID_VALUE_TRIGGER_CONDITION_OPERATORS = {"any", "contains", "<", "<=", "==", ">", ">="}`.
- Validate `value_trigger_condition_operator` in `validate_worker_configure`.
- Validate/coerce `value_trigger_condition_value` as a bounded string. If the
  whitespace decision is trim, trim it here and in the frontend save path.
- Extend `_normalize_value_trigger_fields` to:
  - remove condition fields from unsupported worker types,
  - default missing/invalid operators to `any`,
  - normalize `value_trigger_condition_value` to `""` when the operator is
    `any`,
  - preserve condition fields for eligible workers.
- Initialize modal form fields:
  - `value_trigger_condition_operator: w.value_trigger_condition_operator || "any"`,
  - `value_trigger_condition_value: w.value_trigger_condition_value || ""`.
- Include/delete/normalize those fields in the modal save path beside the
  existing `value_trigger_*` fields.

Exit criteria:

- Existing value-trigger configs round-trip unchanged.
- Unsupported workers do not persist condition fields.
- Legacy workers without condition fields normalize to `any`.

### Phase 2: Server Condition Evaluator

Files:

- `server/events.py`
- `server/templates.py` if a canonical value text helper is extracted
- `tests/test_events.py`
- `tests/test_values.py` if the canonical text helper moves or changes

Tasks:

- Add `_value_trigger_condition_matches(value_event, worker)` next to
  `_value_trigger_matches`.
- Return a structured result:

```python
{
    "matched": True,
    "operator": ">=",
    "configured_value": "5",
    "coerced_value": 5,
    "coerced_value_type": "number",
    "error": None,
}
```

- Implement `any` as an unconditional match.
- Implement numeric relational operators by parsing the configured value with
  the same plain-number grammar used by `server.values.normalize_value_payload`.
  A small public helper may be worth extracting if `_parse_plain_number`
  remains private.
- Implement string relational operators with exact string equality and Unicode
  code-point ordering.
- Implement `contains` as exact case-sensitive substring matching:
  - for string values, search `str(new_value)`,
  - for numeric values, search the canonical raw numeric text.
- Treat unknown/missing `new_value_type` as non-matching for all operators
  except `any`.
- Log filtered condition failures at debug level with enough context to explain
  the non-match.

Exit criteria:

- The evaluator has direct unit or integration coverage for every operator.
- Invalid numeric thresholds return a non-match, not an exception.
- Numeric `contains` does not use display formatting.

### Phase 3: Trigger Pipeline Integration

Files:

- `server/events.py`
- `tests/test_events.py`

Tasks:

- In `_fire_value_change_triggers`, evaluate the condition after scope,
  no-op, pause, and cooldown checks, but before:
  - setting `last_value_trigger_time`,
  - saving layout runtime state,
  - creating a synthetic ticket,
  - scheduling the worker.
- Pass the condition result into `_create_value_trigger_task`.
- Add condition metadata under `task["value_trigger"]["condition"]`.
- Add the ticket body condition line when the operator is not `any`.
- Do not update cooldown or create any ticket when the condition does not
  match.

Exit criteria:

- Filtered value writes leave ticket count, queue state, and
  `last_value_trigger_time` unchanged.
- Passing value writes behave like existing value-change triggers plus metadata.

### Phase 4: Frontend Configuration UI

Files:

- `static/components/WorkerConfigModal.js`
- `tests/test_frontend_value_change_trigger.py`
- Existing modal VM tests if richer behavior needs executable coverage

Tasks:

- Add a comparison selector in the `on_value_change` block with options:
  - Any change: `any`
  - Contains: `contains`
  - Less than: `<`
  - Less than or equal: `<=`
  - Equal to: `==`
  - Greater than: `>`
  - Greater than or equal: `>=`
- Show the comparison value input for every operator except `any`.
- Add computed helpers to identify the currently selected Value worker when the
  scope is `name` or `coord`.
- Show lightweight helper/warning text:
  - numeric + relational: parsed as a number,
  - numeric + `contains`: compares against value text,
  - string + relational ordering: alphabetic/text ordering,
  - any/missing target: interpreted at trigger time.
- Save `contains` without numeric parsing warnings.

Exit criteria:

- The modal round-trips `operator` and `value`.
- The UI does not imply `contains` is numeric for numeric Value workers.
- Existing `on_value_change` controls remain visible and stable.

### Phase 5: Tests

Backend coverage in `tests/test_events.py`:

- Default/missing condition fields behave like `any`.
- Numeric `>= 5` filters out `4.9` and fires on `5`.
- Numeric invalid threshold, such as `5%`, does not fire and does not update
  cooldown.
- Numeric `contains "2"` fires for `123` and not for `345`.
- String `contains "2026"` fires for `release/2026-06`.
- String `contains` is case-sensitive.
- String ordering covers `"10" < "2"` and `"Beta" < "alpha"`.
- Auto values can compare as number on one write and string on a later write.
- Passing tickets include `value_trigger.condition`.

Frontend/source coverage in `tests/test_frontend_value_change_trigger.py`:

- Condition fields initialize from worker config.
- `contains` appears in the selector.
- `any` hides or clears the comparison value.
- Save path keeps condition fields only for eligible `on_value_change` workers.
- Save path deletes condition fields when the activation is not
  `on_value_change`.

Targeted helper coverage:

- If a public numeric parser or canonical raw value text helper is extracted,
  cover it in `tests/test_values.py`.
- If the modal warning logic becomes non-trivial, add a VM-style test rather
  than relying only on source-string assertions.

### Phase 6: Documentation Updates

Files:

- `docs/value-change-trigger.md`
- `docs/value-workers.md` or README MCP section if needed
- `docs/conditional-value-triggers.md`

Tasks:

- Mention that value-change triggers can now be conditional.
- Document that `set_value`, `increment_value`, and `decrement_value` may
  trigger conditional automation when the predicate matches.
- Keep this spec as the detailed source of truth for operator semantics.

### Suggested Implementation Order

1. Backend schema/normalization.
2. Server evaluator with focused tests.
3. Trigger integration and synthetic ticket metadata.
4. Frontend modal controls.
5. Frontend tests and final documentation touchups.

This order keeps the behavior testable before UI polish and avoids a partially
visible control that cannot fire correctly yet.

### Planning Risks

- **Private numeric parser.** `server.values._parse_plain_number` is currently
  private. The clean implementation likely promotes a small public helper or
  adds a wrapper so condition evaluation does not duplicate number parsing.
- **Whitespace semantics.** V1 trims condition values. A future preserve-space
  mode would need explicit UI and validation support rather than reusing the
  current short-field path.
- **Diagnostics minimalism.** Debug logs satisfy v1, but users may still need
  UI feedback later. Keep the evaluator result structured so a diagnostics
  surface can consume it later.
- **Source-string frontend tests.** Several frontend tests assert source text.
  Small markup changes can make these brittle; add executable modal tests if
  warning behavior grows beyond simple rendering.
