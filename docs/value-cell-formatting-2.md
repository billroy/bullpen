# Value Cell Number Formatting — Draft 2

Status: Proposed  
Date: 2026-07-14

## Purpose

Make numeric Value cells easier to read while keeping value entry and storage
predictable.

The essential changes are:

- give General, Number, Currency, Text left, and Text right clear behavior;
- let Number and Currency display thousands separators;
- let Number and Currency use automatic or fixed decimal places;
- classify a value only when a user or API writes it;
- preserve that classification everywhere else; and
- use the same rounding rules in the browser and server.

This is a formatting improvement, not a spreadsheet type system.

## User-visible behavior

### Formats

Bullpen supports these Value formats:

| Format | Display |
|---|---|
| General | Plain value, no added thousands separators or trailing zeros |
| Number | Numeric display with configurable grouping and decimal places |
| Currency | Number behavior with the configured currency symbol |
| Text left | Unformatted text, left-aligned |
| Text right | Unformatted text, right-aligned |

Format Auto is removed from the editor. Existing Format Auto values are treated
as General.

General remains the default. A user selects Number when they want a value such
as `3458734893` displayed as `3,458,734,893`.

### Number and Currency options

Number and Currency expose two controls:

- **Thousands separator:** on or off. The default is on.
- **Decimal places:** Auto or a fixed value from 0 through 10. Auto preserves
  the meaningful decimal digits in the stored number without adding zeros.

Examples in an English-language browser:

| Stored value | Format | Options | Display |
|---:|---|---|---:|
| `3458734893` | General | — | `3458734893` |
| `3458734893` | Number | grouping on, Auto | `3,458,734,893` |
| `1234.5` | Number | grouping on, 2 places | `1,234.50` |
| `1234.5` | Number | grouping off, 2 places | `1234.50` |
| `1234.5` | Currency | `$`, grouping on, 2 places | `$1,234.50` |

Changing Format or its options changes presentation only. It does not change
the stored value, Type, Unit, history, or value-change triggers.

### Alignment

- General follows the resolved value type: numbers align right and strings
  align left.
- Number and Currency align right.
- Text left and Text right use the alignment named by the format.

### Locale

The browser uses its locale for decimal and thousands separators. The server
and MCP formatted representation use `en-US` for deterministic output and also
return the raw value.

## Value classification

Formatting depends on knowing whether a Value is numeric. Classification uses
one small rule: classify only when a new value is written, then store and
preserve the result.

### Browser entry with Type Auto

Plain decimal text is numeric:

```text
^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$
```

Examples:

| Entry | Result |
|---|---|
| `13` | Number |
| `-13.5` | Number |
| `0.5` | Number |
| `00123` | String |
| `1,234` | String |
| `$13` | String |
| `13%` | String |
| `1e5` | String |

This deliberately recognizes only ordinary decimal entry. Type Number may be
selected explicitly when conversion is intended; invalid Number input is
rejected rather than converted to zero.

To avoid silently changing identifiers or losing precision, Auto treats a
numeric-looking entry with more than 15 significant decimal digits as a
String. Explicit Type Number rejects it.

### MCP entry with Type Auto

MCP values already have a JSON type:

- a JSON number is a Number;
- a JSON string is a String, including `"42"`; and
- JSON null is Null.

An MCP client can request conversion by supplying Type Number.

### Classification lifetime

Classification occurs for manual value entry, value replacement, Type changes,
MCP value writes, increments, and raw worksheet paste.

After classification, Bullpen preserves the stored value and resolved type.
Loading, saving, rendering, copying, duplicating, importing, transferring,
restoring, or reading a Value must not reclassify it. Format and Unit changes
must not classify it either.

Legacy values that lack valid type metadata are repaired once during migration.
Ordinary layout normalization validates stored metadata but does not infer a
new type.

## Formatting rules

### General

General displays the stored value without inserting separators or padding
decimal zeros. It does not switch notation based on card width.

### Number

Number applies the chosen grouping and decimal-place options to resolved
numeric values. Auto decimal places do not add trailing zeros. Fixed decimal
places round and pad to the selected count.

### Currency

Currency applies Number formatting and prefixes the configured symbol. This
work retains Bullpen's existing custom-symbol behavior; it does not introduce
currency conversion or country-specific accounting rules.

### Strings

Text formats always display the stored text. If Number or Currency is selected
for a String value, Bullpen displays the string unchanged rather than guessing
or showing zero.

### Rounding

Browser and server use decimal rounding with identical results. Fixed-place
rounding is half away from zero:

| Value | Places | Display |
|---:|---:|---:|
| `1.005` | 2 | `1.01` |
| `-1.005` | 2 | `-1.01` |
| `2.675` | 2 | `2.68` |

The displayed result must not contain `-0`; it displays as `0` with the
requested decimal padding.

## Persistence and update rules

- New Values default to Type Auto and Format General.
- The stored record contains the declared Type and resolved type.
- A successful value write atomically updates value and type metadata, appends
  history when enabled, and emits one value-change event.
- A failed value write changes nothing.
- Format-only and Unit-only writes do not append value history or emit a
  value-change event.
- Configuration dialogs submit only fields changed by the user, so a format
  edit cannot overwrite a newer value.
- Bulk configuration does not accept value, type, or history changes.
- Disabling Save History stops future entries; it does not delete existing
  history.

These rules are sufficient for the lifecycle: entry points classify, and all
structural operations preserve stored state.

## Excel compatibility and notable differences

Bullpen follows Excel's familiar distinction between a minimally decorated
General display and an explicitly grouped Number display. Thousands grouping,
fixed decimal places, currency display, and numeric right-alignment should
therefore feel familiar.

Bullpen does not reproduce Excel's broad input heuristics. It does not
automatically convert dates, percentages, fractions, currency-decorated text,
scientific notation, or localized numeric text. It also does not implement
Accounting, custom format codes, width-dependent General notation, formula
evaluation, or Excel's full precision model.

## Implementation plan

### 1. Establish the classification boundary

- Separate new-value classification from stored-value validation.
- Apply the browser and MCP rules above at value-write entry points.
- Remove inference from layout normalization, reads, saves, and structural
  operations.
- Migrate existing Format Auto values to General and repair missing legacy type
  metadata once.

### 2. Complete the formats

- Remove Format Auto from the editor.
- Implement General and both text alignments.
- Complete grouping and Auto/fixed decimal controls for Number and Currency.
- Share deterministic decimal-rounding behavior between browser and server.
- Ensure format-only saves cannot write value fields.

### 3. Verify the contract

- Add table-driven classification tests for accepted and rejected browser and
  MCP inputs, including precision boundaries.
- Add generated formatting tests across signs, magnitudes, grouping, decimal
  places, rounding ties, Number, and Currency.
- Run the same formatting corpus through server code and real Chromium.
- Add focused integration tests proving that reload, copy, duplicate, import,
  transfer, restore, and unrelated saves preserve value and resolved type.
- Add browser tests for displayed text, alignment, editor controls, and
  format-only updates.

The generated suite should contain thousands of inexpensive formatting cases,
while lifecycle coverage should remain a small set of representative invariant
tests rather than a separate case matrix for every feature.

## Acceptance criteria

- A user can select Number and display ordinary numbers with thousands
  separators.
- Number and Currency support grouping on/off and Auto or 0–10 decimal places.
- General, Number, Currency, Text left, and Text right are visibly distinct.
- Browser and server agree on fixed-place rounding.
- Invalid numeric input never becomes zero.
- Type inference occurs only when a new value is written.
- Stored value and resolved type survive all non-value operations unchanged.
- Format and Unit changes do not alter value history or fire value triggers.
- Existing Format Auto data displays as General.
- The classification and formatting corpus passes in server tests and real
  Chromium.
