# Formula Function Library

## Status

Approved implementation specification for the P0 and P1 formula-function
catalog selected on 2026-07-16. This document extends
`docs/value-cell-formulas.md`; that document remains authoritative for parsing,
references, recalculation, errors, collaboration, and security.

The catalog is intentionally a work surface for agents and people, not an
attempt to reproduce Excel. A function belongs here when it is useful as a
durable, visible calculation that should remain installed in a Value cell and
react when its inputs change. Exploratory and heavy analysis belongs in an
agent using values and history arrays obtained through MCP.

## Scope

This implementation adds 130 functions to the existing 43-function library:

- **P0:** 47 conspicuous calculator primitives and common work transformations.
- **P1:** 83 durable conveniences, including work calendars, lookup helpers,
  descriptive reductions, financial calculations, base conversion, and
  bitwise manipulation.

The Bullpen-native history and worker-data ideas shown alongside the catalog
(`PREVIOUS`, `CHANGE`, JSON extraction, regular expressions, and related
functions) remain separate proposals. They require contracts beyond the
approved Excel-shaped P0/P1 catalog and are not silently included here.

## P0 Catalog

### Date and time

`DATEVALUE`, `EDATE`, `EOMONTH`, `HOUR`, `MINUTE`, `SECOND`, `TIME`,
`TIMEVALUE`, `WEEKDAY`

### Information and logic

`ISNA`, `TYPE`, `IFNA`, `IFS`, `SWITCH`

### Lookup and reference

`INDEX`, `MATCH`, `XLOOKUP`

### Math and aggregation

`CEILING.MATH`, `EXP`, `FLOOR.MATH`, `INT`, `LN`, `LOG`, `LOG10`, `PI`,
`POWER`, `PRODUCT`, `SIGN`, `SQRT`, `SUMIF`, `SUMIFS`, `SUMPRODUCT`, `TRUNC`

### Statistical

`COUNTA`, `COUNTBLANK`, `COUNTIF`, `COUNTIFS`, `MEDIAN`

### Text

`CLEAN`, `FIND`, `NUMBERVALUE`, `REPLACE`, `SEARCH`, `TEXT`, `TEXTAFTER`,
`TEXTBEFORE`, `VALUE`

## P1 Catalog

### Date and time

`DATEDIF`, `ISOWEEKNUM`, `NETWORKDAYS`, `NETWORKDAYS.INTL`, `WEEKNUM`,
`WORKDAY`, `WORKDAY.INTL`, `YEARFRAC`

### Information and logic

`ISERR`, `ISEVEN`, `ISLOGICAL`, `ISODD`, `N`, `NA`, `XOR`

### Lookup and reference

`CHOOSE`, `COLUMN`, `COLUMNS`, `ROW`, `ROWS`, `XMATCH`

### Math and trigonometry

`ACOS`, `ACOSH`, `ASIN`, `ASINH`, `ATAN`, `ATAN2`, `ATANH`, `COMBIN`, `COS`,
`COSH`, `DEGREES`, `FACT`, `GCD`, `LCM`, `QUOTIENT`, `RADIANS`, `SIN`, `SINH`,
`SUMSQ`, `TAN`, `TANH`

### Statistical

`AVERAGEIF`, `AVERAGEIFS`, `LARGE`, `MAXIFS`, `MINIFS`, `PERCENTILE.INC`,
`QUARTILE.INC`, `RANK.EQ`, `SMALL`, `STDEV.P`, `STDEV.S`

### Text

`CHAR`, `CODE`, `EXACT`, `PROPER`, `REPT`, `UNICODE`, `UNICHAR`

### Financial

`IRR`, `MIRR`, `NPER`, `RATE`, `XIRR`, `XNPV`

### Engineering conversion and bitwise operations

`BIN2DEC`, `BIN2HEX`, `BIN2OCT`, `DEC2BIN`, `DEC2HEX`, `DEC2OCT`, `HEX2BIN`,
`HEX2DEC`, `HEX2OCT`, `OCT2BIN`, `OCT2DEC`, `OCT2HEX`, `BITAND`, `BITLSHIFT`,
`BITOR`, `BITRSHIFT`, `BITXOR`

## Common Semantics

- Function names remain case-insensitive and the public catalog is returned by
  `list_formula_functions` through MCP.
- Functions return a scalar. Ranges are accepted only by functions whose
  signatures explicitly allow them.
- Numeric results must be finite. Domain, overflow, and convergence failures
  produce `#NUM!`; invalid types and shapes produce `#VALUE!`; empty numeric
  samples produce `#DIV/0!` where a divisor or sample size is missing.
- Blank range positions are ignored by numeric reductions unless the function
  explicitly counts blanks. Text is not silently parsed as a number by numeric
  functions.
- Optional arguments use the documented Bullpen default. Compatibility is by
  explicit contract rather than accidental inheritance from Python or Excel.
- Operations remain pure, bounded, deterministic, and server-authoritative.
  The only volatile functions remain `NOW`, `TODAY`, `RAND`, and
  `RANDBETWEEN`; the latter two are not part of this approved catalog.

## Criteria and Lookup Semantics

Criteria functions accept a literal value or a string beginning with one of
`=`, `<>`, `<`, `<=`, `>`, or `>=`. A string without an operator compares for
case-insensitive equality. `*` and `?` wildcards are supported for string
equality and inequality; `~` escapes the next wildcard character.

Parallel criteria and result ranges must have the same number of positions.
`SUMIF`, `COUNTIF`, and `AVERAGEIF` accept one criteria range. Their plural
forms apply every criteria pair with logical AND. `MAXIFS` and `MINIFS` reject
an empty matching numeric sample with `#VALUE!`.

`INDEX` uses one-based row and optional column positions. Because formulas do
not expose array results, row or column zero is rejected. `MATCH` and `XMATCH`
default to exact matching; supported match modes and search modes are listed in
MCP metadata. `XLOOKUP` returns the aligned scalar from its return range and
supports an optional not-found value.

## Date Semantics

- Inputs are strict ISO dates or UTC ISO timestamps already used by Value
  formulas. Locale-dependent parsing is not introduced.
- Date-producing functions return ISO `YYYY-MM-DD`; time-producing functions
  return `HH:MM:SS`; date extractors accept either representation where
  unambiguous.
- `WEEKDAY` and `WEEKNUM` support documented Excel-style return modes.
- Workday functions accept an optional holiday range containing ISO dates.
  International weekend codes use the documented two-day and one-day weekend
  mappings; arbitrary seven-character masks are also accepted.
- `YEARFRAC` supports bases 0 through 4. Basis 1 is actual/actual using the
  year lengths crossed; bases 2, 3, and 4 are actual/360, actual/365, and
  European 30/360.

## Engineering Semantics

The expression grammar has no bitwise operators. `^` is exponentiation and `&`
is text concatenation. Boolean `AND`, `OR`, and `NOT` are functions; `XOR` is
added as a Boolean function by this catalog.

Consequently all five bitwise operations are explicit functions. They accept
non-negative integers up to 48 bits. Shift counts are integers; a negative
count reverses the shift direction. Results outside the 48-bit unsigned range
produce `#NUM!`.

Base-conversion functions accept the source representation as text or an
integer where unambiguous. Output is uppercase text. Optional `places` pads the
result and may not truncate it. Signed binary, octal, and hexadecimal inputs
use Excel-compatible fixed-width two's-complement widths of 10, 10, and 10
digits respectively; decimal-to-base functions accept the corresponding
documented signed ranges.

## Financial Semantics

Iterative functions use deterministic bounded solvers with fixed iteration and
tolerance limits. Failure to bracket or converge produces `#NUM!`. Cash-flow
functions require both a negative and a positive cash flow. `XIRR` and `XNPV`
require one ISO date per cash flow and use a 365-day exponent. `MIRR` requires
finance and reinvestment rates. Sign and payment-timing conventions remain
consistent with the existing `PV`, `FV`, `PMT`, and `NPV` functions.

## Test Contract

Every catalog entry must have:

1. Machine-readable signature, category, summary, range capability, and a
   working example exposed through MCP.
2. At least one direct success assertion.
3. Boundary coverage appropriate to its family: arity, type, domain, blank,
   range-shape, date, overflow, or convergence behavior.
4. Representative mixed scalar/range and case-insensitivity coverage.
5. Continued execution of the existing parser, recalculation, collaboration,
   MCP, and frontend suites.
