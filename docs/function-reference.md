# Bullpen Formula Function Reference

This reference documents the 173 public functions returned by Bullpen's
`list_formula_functions` MCP tool. It describes the current server-authoritative
evaluator, not the complete Excel or Google Sheets function set.

## Formula conventions

- A formula begins with `=`, for example `=SUM(A1:A4)`.
- Function names are case-insensitive. This reference uses uppercase names.
- Arguments are separated by commas. Square brackets in a signature mark an
  optional argument; they are documentation notation and are not typed into the
  formula.
- Coordinates such as `A1`, absolute or mixed coordinates such as `$A$1`, and
  rectangular ranges such as `A1:C4` are supported. Range values are row-major.
- A range position without a Value cell is blank. A range cannot be the final
  result of a formula and cannot be used directly in arithmetic.
- Named Value cells can be referenced with a bare simple name or with brackets,
  as in `[cost per unit]`. Coordinate-shaped tokens always mean coordinates.
- Numbers and Booleans are distinct types. Numeric functions do not coerce
  Boolean values or numeric-looking text unless the function explicitly parses
  text, such as `VALUE` or `NUMBERVALUE`.
- Text comparisons used by lookup and criteria functions are
  case-insensitive unless the function says otherwise. `EXACT` is
  case-sensitive.
- Functions return one scalar: a number, text value, or Boolean. In an
  auto-typed Value cell, Boolean results are stored as the text `true` or
  `false`.

## Errors

| Code | Meaning |
|---|---|
| `#PARSE!` | Invalid formula syntax or a parsing limit was exceeded. |
| `#NAME?` | An unknown function or missing named reference was used. |
| `#REF!` | A coordinate or requested range position is invalid. |
| `#VALUE!` | An argument has the wrong type, shape, count, or value. |
| `#DIV/0!` | A divisor is zero or a required numeric sample is empty. |
| `#NUM!` | A numeric domain, overflow, range, or convergence check failed. |
| `#N/A` | A lookup, branch selection, or explicitly unavailable value has no result. |
| `#CYCLE!` | Formula dependencies contain a direct or indirect cycle. |
| `#LIMIT!` | Evaluation exceeded a work, size, depth, or output budget. |

Errors from referenced formula cells propagate unless handled by `IFERROR`,
`IFNA`, or an error-test function. `IF`, `IFS`, `SWITCH`, `AND`, `OR`,
`IFERROR`, and `IFNA` evaluate only the branch or arguments they need.

## Criteria syntax

`COUNTIF`, `COUNTIFS`, `SUMIF`, `SUMIFS`, `AVERAGEIF`, `AVERAGEIFS`, `MAXIFS`,
and `MINIFS` accept either a literal criterion or criterion text. Text may begin
with `=`, `<>`, `<`, `<=`, `>`, or `>=`; without an operator it means equality.
Text equality is case-insensitive. `*` matches any run of characters, `?`
matches one character, and `~` escapes the next wildcard.

## Logic and tests

### `IF`

**Syntax:** `IF(condition, value_if_true, [value_if_false])`

Returns the second argument when `condition` is truthy and the third argument
otherwise. The false result defaults to `FALSE`. Only the selected branch is
evaluated, so an error in the unused branch does not propagate.

**Example:** `=IF(A1>=10,"ready","waiting")`

### `IFERROR`

**Syntax:** `IFERROR(value, fallback)`

Evaluates `value` and returns it if successful. If evaluation produces any
formula error, evaluates and returns `fallback`.

**Example:** `=IFERROR(A1/B1,0)`

### `ISERROR`

**Syntax:** `ISERROR(value)`

Returns `TRUE` when evaluating `value` produces any formula error, including
`#N/A`; otherwise returns `FALSE`. The tested error does not escape the
function.

**Example:** `=ISERROR(1/0)`

### `AND`

**Syntax:** `AND(value1, [value2], ...)`

Returns `TRUE` when every argument is truthy. Requires at least one argument
and stops at the first false argument, so later arguments are not evaluated.

**Example:** `=AND(A1>0,B1<10)`

### `OR`

**Syntax:** `OR(value1, [value2], ...)`

Returns `TRUE` when at least one argument is truthy. Requires at least one
argument and stops at the first true argument.

**Example:** `=OR(A1="blocked",B1="failed")`

### `NOT`

**Syntax:** `NOT(value)`

Returns the logical opposite of the argument's truth value.

**Example:** `=NOT(A1="done")`

### `ISNUMBER`

**Syntax:** `ISNUMBER(value)`

Returns `TRUE` only for a numeric value. Booleans and numeric-looking text such
as `"12"` return `FALSE`.

**Example:** `=ISNUMBER(A1)`

### `ISTEXT`

**Syntax:** `ISTEXT(value)`

Returns `TRUE` when the argument is text and `FALSE` for numbers and Booleans.

**Example:** `=ISTEXT(A1)`

### `ISBLANK`

**Syntax:** `ISBLANK(value)`

Returns `TRUE` for a blank value or empty text and `FALSE` otherwise.

**Example:** `=ISBLANK(A1)`

### `ISNA`

**Syntax:** `ISNA(value)`

Returns `TRUE` only when evaluating `value` produces `#N/A`. Other errors return
`FALSE` from this test.

**Example:** `=ISNA(NA())`

### `TYPE`

**Syntax:** `TYPE(value)`

Returns a numeric type code: `1` for a number, `2` for text or another scalar
type, `4` for a Boolean, and `64` for a range.

**Example:** `=TYPE(A1:A3)`

### `IFNA`

**Syntax:** `IFNA(value, fallback)`

Returns `fallback` only when `value` produces `#N/A`. Other errors continue to
propagate. The fallback is evaluated only when needed.

**Example:** `=IFNA(XLOOKUP(A1,B1:B5,C1:C5),"not found")`

### `IFS`

**Syntax:** `IFS(condition1, value1, ...)`

Accepts one or more condition/result pairs and returns the result belonging to
the first truthy condition. Pairs are tested from left to right. Returns
`#N/A` if no condition is true.

**Example:** `=IFS(A1>=90,"high",A1>=50,"medium",TRUE,"low")`

### `SWITCH`

**Syntax:** `SWITCH(expression, value1, result1, ..., [default])`

Compares `expression` with each case value in order and returns the first
matching result. Text comparison is case-insensitive. If no case matches,
returns the optional final default or `#N/A` when no default was supplied.

**Example:** `=SWITCH(A1,"open",1,"closed",0,-1)`

### `ISERR`

**Syntax:** `ISERR(value)`

Returns `TRUE` for any formula error except `#N/A`. Returns `FALSE` for a
successful value and for `#N/A`.

**Example:** `=ISERR(1/0)`

### `ISEVEN`

**Syntax:** `ISEVEN(number)`

Truncates `number` toward zero and returns whether the resulting integer is
even. Non-numeric arguments produce `#VALUE!`.

**Example:** `=ISEVEN(4.9)`

### `ISLOGICAL`

**Syntax:** `ISLOGICAL(value)`

Returns `TRUE` only when the evaluated argument is a Boolean.

**Example:** `=ISLOGICAL(A1>0)`

### `ISODD`

**Syntax:** `ISODD(number)`

Truncates `number` toward zero and returns whether the resulting integer is
odd. Non-numeric arguments produce `#VALUE!`.

**Example:** `=ISODD(3.9)`

### `N`

**Syntax:** `N(value)`

Returns a number unchanged, converts `TRUE` to `1` and `FALSE` to `0`, and
returns `0` for text and other non-numeric scalar values.

**Example:** `=N(TRUE)`

### `NA`

**Syntax:** `NA()`

Produces the `#N/A` error deliberately. This is useful for marking an
unavailable result or exercising `IFNA` and `ISNA`.

**Example:** `=IFNA(NA(),"pending")`

### `XOR`

**Syntax:** `XOR(value1, ...)`

Returns `TRUE` when an odd number of the flattened arguments are truthy.
Requires at least one argument.

**Example:** `=XOR(TRUE,FALSE,TRUE)`

## Lookup and reference

Lookup functions compare text case-insensitively. Positions returned by
`INDEX`, `MATCH`, `XMATCH`, `ROW`, and `COLUMN` are one-based.

### `INDEX`

**Syntax:** `INDEX(range, row, [column])`

Returns the scalar at a one-based row and column within `range`. `column`
defaults to `1`. A scalar is treated as a one-cell range. Row or column zero is
not an array shortcut; any position outside the supplied range returns
`#REF!`.

**Example:** `=INDEX(A1:C3,2,3)`

### `MATCH`

**Syntax:** `MATCH(value, range, [match_type])`

Returns the one-based position of a value in the flattened range. `match_type`
defaults to `1`: exact match first, otherwise the largest numeric value less
than or equal to the lookup value. Use `0` for exact matching or `-1` for the
smallest numeric value greater than or equal to the lookup value. Returns
`#N/A` when no candidate exists.

**Example:** `=MATCH("ready",A1:A10,0)`

### `XLOOKUP`

**Syntax:** `XLOOKUP(value, lookup_range, return_range, [not_found], [match_mode], [search_mode])`

Searches aligned, equally sized ranges and returns the corresponding scalar
from `return_range`. `match_mode` defaults to `0` (exact); `1` selects the next
larger numeric value, `-1` the next smaller numeric value, and `2` enables
wildcards. `search_mode` is `1` for first-to-last or `-1` for last-to-first.
Returns `not_found` when supplied, otherwise `#N/A`.

**Example:** `=XLOOKUP(A1,B1:B10,C1:C10,"missing",0,1)`

### `CHOOSE`

**Syntax:** `CHOOSE(index, value1, ...)`

Returns the value at the one-based `index` following the index argument.
Requires at least one candidate. An index below `1` or beyond the candidate
list produces `#VALUE!`.

**Example:** `=CHOOSE(2,"red","green","blue")`

### `COLUMN`

**Syntax:** `COLUMN([reference])`

Returns the one-based column number of a coordinate reference. With no
argument, returns the formula cell's own column. A supplied argument must be a
coordinate or coordinate range, not a named reference or calculated scalar.

**Example:** `=COLUMN(C8)`

### `COLUMNS`

**Syntax:** `COLUMNS(range)`

Returns the number of columns in a rectangular range. A scalar counts as one
column.

**Example:** `=COLUMNS(B2:D8)`

### `ROW`

**Syntax:** `ROW([reference])`

Returns the one-based row number of a coordinate reference. With no argument,
returns the formula cell's own row. A supplied argument must be a coordinate or
coordinate range.

**Example:** `=ROW(C8)`

### `ROWS`

**Syntax:** `ROWS(range)`

Returns the number of rows in a rectangular range. A scalar counts as one row.

**Example:** `=ROWS(B2:D8)`

### `XMATCH`

**Syntax:** `XMATCH(value, range, [match_mode], [search_mode])`

Returns a one-based position. `match_mode` defaults to `0` (exact); `1` means
exact or next larger, `-1` exact or next smaller, and `2` enables wildcards.
`search_mode` defaults to `1` (first-to-last); use `-1` for last-to-first.
Returns `#N/A` if no match is available.

**Example:** `=XMATCH("ready",A1:A10,0,-1)`

## Math and aggregation

Numeric reductions flatten range arguments in row-major order. They include
numbers and ignore blanks, text, and Booleans unless stated otherwise.

### `SUM`

**Syntax:** `SUM(value1, [value2], ...)`

Adds all numeric scalar and range items. Non-numeric items are ignored. Returns
`0` when there are no numeric items.

**Example:** `=SUM(A1:A10,25)`

### `AVERAGE`

**Syntax:** `AVERAGE(value1, [value2], ...)`

Returns the arithmetic mean of all numeric scalar and range items. Non-numeric
items are ignored. Returns `#DIV/0!` when no numeric item is available.

**Example:** `=AVERAGE(A1:A10)`

### `MIN`

**Syntax:** `MIN(value1, [value2], ...)`

Returns the smallest numeric scalar or range item. Non-numeric items are
ignored. Returns `#VALUE!` when no numeric item is available.

**Example:** `=MIN(A1:A10,0)`

### `MAX`

**Syntax:** `MAX(value1, [value2], ...)`

Returns the largest numeric scalar or range item. Non-numeric items are
ignored. Returns `#VALUE!` when no numeric item is available.

**Example:** `=MAX(A1:A10,100)`

### `COUNT`

**Syntax:** `COUNT(value1, [value2], ...)`

Counts numeric scalar and range items. Blanks, text, and Booleans are not
counted.

**Example:** `=COUNT(A1:C10)`

### `ABS`

**Syntax:** `ABS(number)`

Returns the non-negative absolute value of `number`.

**Example:** `=ABS(-12.5)`

### `ROUND`

**Syntax:** `ROUND(number, [digits])`

Rounds to `digits` decimal places using half-up rounding; a halfway magnitude
is rounded away from zero. `digits` defaults to `0` and may be negative to
round to tens, hundreds, and so on. Extremely large digit counts produce
`#LIMIT!`.

**Example:** `=ROUND(12.345,2)`

### `ROUNDUP`

**Syntax:** `ROUNDUP(number, [digits])`

Rounds away from zero at the requested decimal position. `digits` defaults to
`0` and may be negative.

**Example:** `=ROUNDUP(12.301,2)`

### `ROUNDDOWN`

**Syntax:** `ROUNDDOWN(number, [digits])`

Rounds toward zero at the requested decimal position. `digits` defaults to `0`
and may be negative.

**Example:** `=ROUNDDOWN(12.399,2)`

### `MOD`

**Syntax:** `MOD(number, divisor)`

Returns the remainder of division. The result follows the divisor's sign.
A zero divisor produces `#DIV/0!`.

**Example:** `=MOD(17,5)`

### `DELTA`

**Syntax:** `DELTA(number1, [number2])`

Returns `1` when the numbers are equal and `0` otherwise. `number2` defaults to
`0`.

**Example:** `=DELTA(A1,B1)`

### `GESTEP`

**Syntax:** `GESTEP(number, [step])`

Returns `1` when `number` is greater than or equal to `step`, otherwise `0`.
`step` defaults to `0`.

**Example:** `=GESTEP(A1,10)`

### `CEILING.MATH`

**Syntax:** `CEILING.MATH(number, [significance], [mode])`

Rounds up to a multiple of the absolute `significance`, which defaults to `1`.
Positive numbers round toward positive infinity. Negative numbers also round
toward positive infinity unless `mode` is truthy, in which case they round
away from zero. A zero significance returns `0`.

**Example:** `=CEILING.MATH(-4.2,1,TRUE)`

### `EXP`

**Syntax:** `EXP(number)`

Returns Euler's number raised to `number`. Overflow or a non-finite result
produces `#NUM!`.

**Example:** `=EXP(1)`

### `FLOOR.MATH`

**Syntax:** `FLOOR.MATH(number, [significance], [mode])`

Rounds down to a multiple of the absolute `significance`, which defaults to
`1`. Positive numbers round toward negative infinity. Negative numbers also
round toward negative infinity unless `mode` is truthy, in which case they
round toward zero. A zero significance returns `0`.

**Example:** `=FLOOR.MATH(-4.8,1,TRUE)`

### `INT`

**Syntax:** `INT(number)`

Returns the greatest integer less than or equal to `number`. This differs from
`TRUNC` for negative non-integers.

**Example:** `=INT(-4.2)`

### `LN`

**Syntax:** `LN(number)`

Returns the natural logarithm. Values less than or equal to zero produce
`#NUM!`.

**Example:** `=LN(2)`

### `LOG`

**Syntax:** `LOG(number, [base])`

Returns the logarithm of `number` in `base`; the base defaults to `10`.
`number` and `base` must be positive, and the base cannot be `1`.

**Example:** `=LOG(8,2)`

### `LOG10`

**Syntax:** `LOG10(number)`

Returns the base-10 logarithm. Values less than or equal to zero produce
`#NUM!`.

**Example:** `=LOG10(1000)`

### `PI`

**Syntax:** `PI()`

Returns the mathematical constant π as a floating-point number.

**Example:** `=PI()`

### `POWER`

**Syntax:** `POWER(number, power)`

Raises `number` to `power`. Invalid real-number domains and overflow produce
`#NUM!`; exponents beyond the evaluator's work budget produce `#LIMIT!`.

**Example:** `=POWER(2,10)`

### `PRODUCT`

**Syntax:** `PRODUCT(value1, ...)`

Multiplies numeric scalar and range items, ignoring blanks, text, and Booleans.
Returns `1` when no numeric item is supplied.

**Example:** `=PRODUCT(A1:A4,2)`

### `SIGN`

**Syntax:** `SIGN(number)`

Returns `-1` for a negative number, `0` for zero, and `1` for a positive
number.

**Example:** `=SIGN(A1)`

### `SQRT`

**Syntax:** `SQRT(number)`

Returns the non-negative square root. A negative argument produces `#NUM!`.

**Example:** `=SQRT(81)`

### `SUMIF`

**Syntax:** `SUMIF(criteria_range, criterion, [sum_range])`

Sums numeric positions whose aligned criterion positions match. When
`sum_range` is omitted, matching numeric values from `criteria_range` are
summed. The criteria and sum ranges must contain the same number of positions;
non-numeric selected result values are ignored.

**Example:** `=SUMIF(A1:A10,">=10",B1:B10)`

### `SUMIFS`

**Syntax:** `SUMIFS(sum_range, criteria_range1, criterion1, ...)`

Sums numeric positions in `sum_range` for which every aligned criterion is
true. Requires at least one range/criterion pair, and all participating ranges
must contain the same number of positions.

**Example:** `=SUMIFS(C1:C10,A1:A10,"open",B1:B10,">0")`

### `SUMPRODUCT`

**Syntax:** `SUMPRODUCT(range1, ...)`

Multiplies aligned items from each argument and adds those products. Arguments
must have equal numbers of positions. A non-numeric item contributes zero to
its position. Requires at least one argument.

**Example:** `=SUMPRODUCT(A1:A4,B1:B4)`

### `TRUNC`

**Syntax:** `TRUNC(number)`

Discards the fractional portion and returns the integer toward zero. Bullpen's
current form accepts no decimal-digits argument.

**Example:** `=TRUNC(-4.8)`

## Math and trigonometry

Angles consumed and returned by trigonometric functions are radians unless a
function explicitly converts units.

### `ACOS`

**Syntax:** `ACOS(number)`

Returns the arccosine in radians. The argument must be from `-1` through `1`;
otherwise the result is `#NUM!`.

**Example:** `=ACOS(0.5)`

### `ACOSH`

**Syntax:** `ACOSH(number)`

Returns the inverse hyperbolic cosine. The argument must be at least `1`.

**Example:** `=ACOSH(2)`

### `ASIN`

**Syntax:** `ASIN(number)`

Returns the arcsine in radians. The argument must be from `-1` through `1`.

**Example:** `=ASIN(0.5)`

### `ASINH`

**Syntax:** `ASINH(number)`

Returns the inverse hyperbolic sine.

**Example:** `=ASINH(1)`

### `ATAN`

**Syntax:** `ATAN(number)`

Returns the arctangent in radians, in the interval from `-π/2` to `π/2`.

**Example:** `=ATAN(1)`

### `ATANH`

**Syntax:** `ATANH(number)`

Returns the inverse hyperbolic tangent. The argument must be strictly between
`-1` and `1`.

**Example:** `=ATANH(0.5)`

### `COS`

**Syntax:** `COS(number)`

Returns the cosine of a radian angle.

**Example:** `=COS(PI())`

### `COSH`

**Syntax:** `COSH(number)`

Returns the hyperbolic cosine. Overflow produces `#NUM!`.

**Example:** `=COSH(1)`

### `DEGREES`

**Syntax:** `DEGREES(number)`

Converts a radian angle to degrees.

**Example:** `=DEGREES(PI())`

### `RADIANS`

**Syntax:** `RADIANS(number)`

Converts an angle in degrees to radians.

**Example:** `=RADIANS(180)`

### `SIN`

**Syntax:** `SIN(number)`

Returns the sine of a radian angle.

**Example:** `=SIN(PI()/2)`

### `SINH`

**Syntax:** `SINH(number)`

Returns the hyperbolic sine. Overflow produces `#NUM!`.

**Example:** `=SINH(1)`

### `TAN`

**Syntax:** `TAN(number)`

Returns the tangent of a radian angle.

**Example:** `=TAN(PI()/4)`

### `TANH`

**Syntax:** `TANH(number)`

Returns the hyperbolic tangent.

**Example:** `=TANH(1)`

### `ATAN2`

**Syntax:** `ATAN2(x, y)`

Returns the angle in radians from the positive x-axis to the point `(x, y)`,
using the signs of both coordinates to choose the quadrant. When both
coordinates are zero, returns `#DIV/0!`.

**Example:** `=ATAN2(1,1)`

### `COMBIN`

**Syntax:** `COMBIN(number, chosen)`

Returns the number of ways to choose `chosen` items from `number` items without
regard to order. Arguments are truncated to integers and must be non-negative;
invalid combinations produce `#NUM!`. Very large inputs are work-limited.

**Example:** `=COMBIN(10,3)`

### `FACT`

**Syntax:** `FACT(number)`

Returns the factorial of the argument after truncating it to an integer.
Negative values produce `#NUM!`; values above `170` are rejected to prevent
overflow.

**Example:** `=FACT(5)`

### `GCD`

**Syntax:** `GCD(number1, ...)`

Returns the greatest common divisor of one or more numbers. Arguments are
truncated to non-negative integers.

**Example:** `=GCD(24,36)`

### `LCM`

**Syntax:** `LCM(number1, ...)`

Returns the least common multiple of one or more numbers. Arguments are
truncated to non-negative integers.

**Example:** `=LCM(6,8)`

### `QUOTIENT`

**Syntax:** `QUOTIENT(numerator, denominator)`

Returns the integer portion of the division result, truncated toward zero. A
zero denominator produces `#DIV/0!`.

**Example:** `=QUOTIENT(-17,5)`

### `SUMSQ`

**Syntax:** `SUMSQ(value1, ...)`

Squares each numeric scalar or range item and returns their sum. Blanks, text,
and Booleans are ignored; no numeric items produce `0`.

**Example:** `=SUMSQ(A1:A4,3)`

## Statistical

Statistical reductions use numeric values only unless the function explicitly
counts other types. Text that merely looks numeric is not parsed.

### `COUNTA`

**Syntax:** `COUNTA(value1, ...)`

Counts every non-blank scalar or range position. Numbers, text, and Booleans
are counted; blank values and empty text are not.

**Example:** `=COUNTA(A1:C10)`

### `COUNTBLANK`

**Syntax:** `COUNTBLANK(value1, ...)`

Counts blank range positions, blank values, and empty text. Other values are
not counted.

**Example:** `=COUNTBLANK(A1:C10)`

### `COUNTIF`

**Syntax:** `COUNTIF(criteria_range, criterion)`

Counts positions in `criteria_range` that match one literal or text criterion.
See [Criteria syntax](#criteria-syntax) for operators and wildcards.

**Example:** `=COUNTIF(A1:A10,"open")`

### `COUNTIFS`

**Syntax:** `COUNTIFS(criteria_range1, criterion1, ...)`

Counts positions for which every aligned range/criterion pair matches.
Requires at least one pair, and every criteria range must contain the same
number of positions.

**Example:** `=COUNTIFS(A1:A10,"open",B1:B10,">=10")`

### `MEDIAN`

**Syntax:** `MEDIAN(value1, ...)`

Returns the median of numeric scalar and range items. Non-numeric items are
ignored. For an even-sized sample it averages the two center values; an empty
numeric sample produces `#DIV/0!`.

**Example:** `=MEDIAN(A1:A10)`

### `AVERAGEIF`

**Syntax:** `AVERAGEIF(criteria_range, criterion, [average_range])`

Returns the mean of numeric positions whose aligned criterion positions match.
When `average_range` is omitted, matching numeric values in `criteria_range`
are averaged. Equal range sizes are required. No matching numeric values
produce `#DIV/0!`.

**Example:** `=AVERAGEIF(A1:A10,"open",B1:B10)`

### `AVERAGEIFS`

**Syntax:** `AVERAGEIFS(average_range, criteria_range1, criterion1, ...)`

Returns the mean of numeric positions in `average_range` for which every
criterion matches. All ranges must be equally sized. No matching numeric values
produce `#DIV/0!`.

**Example:** `=AVERAGEIFS(C1:C10,A1:A10,"open",B1:B10,">0")`

### `LARGE`

**Syntax:** `LARGE(range, rank)`

Returns the `rank`th largest numeric value, where rank `1` is the maximum.
`rank` is converted to an integer and must be between `1` and the numeric
sample size; otherwise the result is `#NUM!`.

**Example:** `=LARGE(A1:A10,2)`

### `MAXIFS`

**Syntax:** `MAXIFS(max_range, criteria_range1, criterion1, ...)`

Returns the largest numeric value whose aligned criteria all match. All ranges
must be equally sized. An empty matching numeric sample produces `#VALUE!`.

**Example:** `=MAXIFS(C1:C10,A1:A10,"open")`

### `MINIFS`

**Syntax:** `MINIFS(min_range, criteria_range1, criterion1, ...)`

Returns the smallest numeric value whose aligned criteria all match. All
ranges must be equally sized. An empty matching numeric sample produces
`#VALUE!`.

**Example:** `=MINIFS(C1:C10,A1:A10,"open")`

### `PERCENTILE.INC`

**Syntax:** `PERCENTILE.INC(range, k)`

Returns the inclusive percentile of the numeric values using linear
interpolation between adjacent sorted values. `k` must be from `0` through `1`.
An empty sample produces `#DIV/0!`; an out-of-range percentile produces
`#NUM!`.

**Example:** `=PERCENTILE.INC(A1:A10,0.9)`

### `QUARTILE.INC`

**Syntax:** `QUARTILE.INC(range, quartile)`

Returns an inclusive quartile by evaluating percentile
`quartile / 4`. `quartile` must be an integer from `0` through `4`, where `0`
is the minimum and `4` is the maximum.

**Example:** `=QUARTILE.INC(A1:A10,2)`

### `RANK.EQ`

**Syntax:** `RANK.EQ(number, range, [order])`

Returns the one-based rank of `number` among the numeric range values. By
default or when `order` is false, the largest value ranks first; a truthy
`order` ranks the smallest first. Equal values receive the same first matching
rank. A number absent from the range produces `#N/A`.

**Example:** `=RANK.EQ(A1,A1:A10,0)`

### `SMALL`

**Syntax:** `SMALL(range, rank)`

Returns the `rank`th smallest numeric value, where rank `1` is the minimum.
An invalid rank produces `#NUM!`.

**Example:** `=SMALL(A1:A10,2)`

### `STDEV.P`

**Syntax:** `STDEV.P(range)`

Returns population standard deviation for the numeric range items. The current
evaluator also accepts multiple scalar or range arguments and flattens them.
Non-numeric items are ignored. An empty numeric sample produces `#DIV/0!`; one
numeric value validly returns `0`.

**Example:** `=STDEV.P(A1:A10)`

### `STDEV.S`

**Syntax:** `STDEV.S(value1, value2, ...)`

Returns sample standard deviation for numeric scalar and range items using an
`n - 1` denominator. At least two numeric values are required; otherwise the
result is `#DIV/0!`.

**Example:** `=STDEV.S(A1:A10)`

## Text

When a text function accepts another scalar type, Bullpen renders Booleans as
lowercase `true` or `false` and blanks as empty text.

### `CONCAT`

**Syntax:** `CONCAT(value1, [value2], ...)`

Flattens scalar and range arguments in row-major order and joins their text
representations without a delimiter. Blank values are omitted. Excessively
long output produces `#LIMIT!`.

**Example:** `=CONCAT(A1:A3,"!")`

### `TEXTJOIN`

**Syntax:** `TEXTJOIN(delimiter, ignore_empty, text1, [text2], ...)`

Flattens the text arguments and joins them with `delimiter`. When
`ignore_empty` is truthy, blank values and empty text are omitted; otherwise
they create empty fields. Requires at least one text argument after the first
two parameters.

**Example:** `=TEXTJOIN(", ",TRUE,A1:A5)`

### `LEFT`

**Syntax:** `LEFT(text, [count])`

Returns the first `count` characters. `count` defaults to `1`; a negative count
produces `#VALUE!`.

**Example:** `=LEFT("Bullpen",4)`

### `RIGHT`

**Syntax:** `RIGHT(text, [count])`

Returns the last `count` characters. `count` defaults to `1`; zero returns
empty text and a negative count produces `#VALUE!`.

**Example:** `=RIGHT("Bullpen",3)`

### `MID`

**Syntax:** `MID(text, start, count)`

Returns up to `count` characters beginning at the one-based `start` position.
`start` must be at least `1`, and `count` cannot be negative. A start beyond the
text returns empty text.

**Example:** `=MID("Bullpen",2,3)`

### `LEN`

**Syntax:** `LEN(text)`

Returns the number of Unicode characters in the text representation of the
argument.

**Example:** `=LEN("Bullpen")`

### `TRIM`

**Syntax:** `TRIM(text)`

Removes leading and trailing whitespace and collapses each internal run of
whitespace to one ordinary space.

**Example:** `=TRIM("  agent   ready  ")`

### `UPPER`

**Syntax:** `UPPER(text)`

Returns text converted to uppercase using Unicode case rules.

**Example:** `=UPPER("Bullpen")`

### `LOWER`

**Syntax:** `LOWER(text)`

Returns text converted to lowercase using Unicode case rules.

**Example:** `=LOWER("Bullpen")`

### `SUBSTITUTE`

**Syntax:** `SUBSTITUTE(text, old_text, new_text, [occurrence])`

Replaces every occurrence of `old_text` when `occurrence` is omitted. When a
positive one-based occurrence is supplied, only that occurrence is replaced;
an occurrence beyond the available matches leaves the text unchanged. Output
is subject to the formula length budget.

**Example:** `=SUBSTITUTE("a-b-a","a","x",2)`

### `CLEAN`

**Syntax:** `CLEAN(text)`

Removes characters with Unicode code points below `32`, covering the C0
control-character range, and leaves other characters unchanged.

**Example:** `=CLEAN(A1)`

### `FIND`

**Syntax:** `FIND(find_text, within_text, [start])`

Returns the one-based position of the first case-sensitive match at or after
the one-based `start`, which defaults to `1`. A missing match or invalid start
produces `#VALUE!`.

**Example:** `=FIND("P","BullPen")`

### `NUMBERVALUE`

**Syntax:** `NUMBERVALUE(text, [decimal_separator], [group_separator])`

Parses text into a number using explicit separators. The decimal separator
defaults to `"."` and the group separator to `","`. A trailing percent sign
divides the parsed value by 100. The decimal separator must be one character;
the group separator may be one character or empty, and the two cannot be
equal.

**Example:** `=NUMBERVALUE("1.234,5",",",".")`

### `REPLACE`

**Syntax:** `REPLACE(text, start, count, replacement)`

Removes `count` characters beginning at the one-based `start` and inserts
`replacement`. `start` must be at least `1`, and `count` cannot be negative.

**Example:** `=REPLACE("abcde",2,3,"X")`

### `SEARCH`

**Syntax:** `SEARCH(find_text, within_text, [start])`

Returns the one-based position of the first case-insensitive literal match at
or after `start`, which defaults to `1`. Wildcards are not interpreted by this
function. A missing match produces `#VALUE!`.

**Example:** `=SEARCH("P","Bullpen")`

### `TEXT`

**Syntax:** `TEXT(value, format)`

Formats numeric values with Bullpen's bounded numeric pattern subset. Digits
after `.` choose fixed decimal places, a comma before the decimal enables
thousands grouping, and `%` multiplies by 100 and appends a percent sign.
Non-numeric values are returned as canonical text; date-pattern formatting is
not supported.

**Example:** `=TEXT(1234.5,"#,##0.00")`

### `TEXTAFTER`

**Syntax:** `TEXTAFTER(text, delimiter, [instance])`

Returns the text after a selected delimiter occurrence. `instance` defaults to
`1`; a positive value counts from the start and a negative value from the end.
An empty delimiter or zero instance produces `#VALUE!`; a missing occurrence
produces `#N/A`.

**Example:** `=TEXTAFTER("a:b:c",":",-1)`

### `TEXTBEFORE`

**Syntax:** `TEXTBEFORE(text, delimiter, [instance])`

Returns the text before a selected delimiter occurrence. `instance` defaults
to `1`; positive instances count from the start and negative instances from
the end. Invalid delimiter or instance values produce the same errors as
`TEXTAFTER`.

**Example:** `=TEXTBEFORE("a:b:c",":",2)`

### `VALUE`

**Syntax:** `VALUE(text)`

Parses text using `"."` as the decimal separator and `","` as the group
separator. Leading and trailing whitespace is ignored, and a trailing percent
sign divides the result by 100. Invalid numeric text produces `#VALUE!`.

**Example:** `=VALUE("1,234.5")`

### `CHAR`

**Syntax:** `CHAR(code)`

Returns the character for an integer code from `1` through `255`. The numeric
argument is truncated before validation; values outside that range produce
`#VALUE!`.

**Example:** `=CHAR(65)`

### `CODE`

**Syntax:** `CODE(text)`

Returns the Unicode code point of the first character. Empty text produces
`#VALUE!`.

**Example:** `=CODE("A")`

### `EXACT`

**Syntax:** `EXACT(text1, text2)`

Returns `TRUE` when the canonical text forms are exactly equal, including
letter case, and `FALSE` otherwise.

**Example:** `=EXACT("Bullpen","bullpen")`

### `PROPER`

**Syntax:** `PROPER(text)`

Uses Unicode title-casing to uppercase the first cased character of each word
and lowercase the remaining cased characters.

**Example:** `=PROPER("agent work")`

### `REPT`

**Syntax:** `REPT(text, count)`

Repeats text `count` times after truncating the count to an integer. A negative
count produces `#VALUE!`; output beyond the formula length budget produces
`#LIMIT!`.

**Example:** `=REPT("ab",3)`

### `UNICODE`

**Syntax:** `UNICODE(text)`

Returns the Unicode code point of the first character. In the current
evaluator this has the same behavior as `CODE`. Empty text produces `#VALUE!`.

**Example:** `=UNICODE("☃")`

### `UNICHAR`

**Syntax:** `UNICHAR(code)`

Returns the Unicode character for the truncated numeric code point. An invalid
code point produces `#VALUE!`.

**Example:** `=UNICHAR(9731)`

## Date and time

Date inputs are strict ISO dates such as `2026-07-18` or ISO timestamps whose
first ten characters are a date. Time inputs are strict ISO times such as
`14:30:00` or the time portion of an ISO timestamp. Bullpen does not parse
locale-specific date text. Date-producing functions return `YYYY-MM-DD`; time
functions return `HH:MM:SS`.

For international workday functions, weekend code `1` means Saturday/Sunday;
codes `2` through `7` move the two-day weekend forward one day at a time.
Codes `11` through `17` select Sunday through Saturday respectively as the
only weekend day. A seven-character Monday-first mask such as `"0000011"` is
also accepted, where `1` marks a weekend.

### `DATE`

**Syntax:** `DATE(year, month, day)`

Constructs a strict ISO date. Unlike spreadsheet functions that normalize
overflowing parts, Bullpen requires an actual calendar year, month, and day;
invalid combinations produce `#NUM!`.

**Example:** `=DATE(2026,7,18)`

### `YEAR`

**Syntax:** `YEAR(date)`

Returns the four-digit year from a strict ISO date or timestamp.

**Example:** `=YEAR("2026-07-18")`

### `MONTH`

**Syntax:** `MONTH(date)`

Returns the month number from `1` through `12` from a strict ISO date or
timestamp.

**Example:** `=MONTH("2026-07-18")`

### `DAY`

**Syntax:** `DAY(date)`

Returns the day of the month from a strict ISO date or timestamp.

**Example:** `=DAY("2026-07-18")`

### `DAYS`

**Syntax:** `DAYS(end_date, start_date)`

Returns the signed number of calendar days from `start_date` to `end_date`.
The result is negative when the end precedes the start.

**Example:** `=DAYS("2026-07-18","2026-07-01")`

### `NOW`

**Syntax:** `NOW()`

Returns the current server-provided time represented in the workspace timezone,
to whole seconds. UTC results use a trailing `Z`; other zones include their
numeric UTC offset. `NOW` is volatile: Bullpen marks it stale after its
freshness interval and recalculates it on workspace activation, dependency
recalculation, or an explicit recalculation request rather than running a
per-cell timer.

**Example:** `=NOW()`

### `TODAY`

**Syntax:** `TODAY()`

Returns the current date in the workspace timezone. It is volatile and becomes
stale at the next workspace-local midnight; recalculation follows Bullpen's
activation and explicit-recalculation policy.

**Example:** `=TODAY()`

### `DATEVALUE`

**Syntax:** `DATEVALUE(iso_date)`

Validates and returns a strict ISO date as `YYYY-MM-DD`. Bullpen returns date
text rather than an Excel-style serial day number.

**Example:** `=DATEVALUE("2026-07-18")`

### `EDATE`

**Syntax:** `EDATE(iso_date, months)`

Moves a date by a truncated integer number of months. If the original day does
not exist in the target month, it is clamped to that month's last day.

**Example:** `=EDATE("2026-01-31",1)`

### `EOMONTH`

**Syntax:** `EOMONTH(iso_date, months)`

Moves by a truncated integer number of months and returns the last day of the
target month.

**Example:** `=EOMONTH("2026-01-10",1)`

### `HOUR`

**Syntax:** `HOUR(iso_time)`

Returns the hour component from `0` through `23` of a strict ISO time or
timestamp.

**Example:** `=HOUR("14:30:45")`

### `MINUTE`

**Syntax:** `MINUTE(iso_time)`

Returns the minute component from `0` through `59` of a strict ISO time or
timestamp.

**Example:** `=MINUTE("14:30:45")`

### `SECOND`

**Syntax:** `SECOND(iso_time)`

Returns the whole-second component from `0` through `59` of a strict ISO time
or timestamp.

**Example:** `=SECOND("14:30:45")`

### `TIME`

**Syntax:** `TIME(hour, minute, second)`

Truncates all three arguments, converts them to a total number of seconds, and
returns a normalized `HH:MM:SS` value. Non-negative totals wrap every 24 hours;
a negative total produces `#NUM!`.

**Example:** `=TIME(25,30,0)`

### `TIMEVALUE`

**Syntax:** `TIMEVALUE(iso_time)`

Validates a strict ISO time or timestamp and returns `HH:MM:SS`, discarding
fractional seconds. Bullpen returns time text rather than a fraction of a day.

**Example:** `=TIMEVALUE("14:30:45")`

### `WEEKDAY`

**Syntax:** `WEEKDAY(iso_date, [return_type])`

Returns a weekday number. The default type `1` maps Sunday through Saturday to
`1` through `7`; type `2` maps Monday through Sunday to `1` through `7`; type
`3` maps Monday through Sunday to `0` through `6`. Types `11` through `17`
return `1` through `7` with the week starting on Monday through Sunday
respectively. Unsupported types produce `#NUM!`.

**Example:** `=WEEKDAY("2026-07-18",2)`

### `DATEDIF`

**Syntax:** `DATEDIF(start_date, end_date, unit)`

Returns a completed date difference. Supported units are `"Y"` for complete
years, `"M"` for complete months, `"D"` for calendar days, `"YM"` for months
after complete years, `"MD"` for days after complete months, and `"YD"` for
days after complete years. An end date before the start produces `#NUM!`; an
unknown unit produces `#VALUE!`.

**Example:** `=DATEDIF("2025-01-01","2026-07-18","M")`

### `ISOWEEKNUM`

**Syntax:** `ISOWEEKNUM(iso_date)`

Returns the ISO 8601 week number, where weeks start Monday and week 1 contains
the year's first Thursday.

**Example:** `=ISOWEEKNUM("2026-07-18")`

### `NETWORKDAYS`

**Syntax:** `NETWORKDAYS(start_date, end_date, [holidays])`

Counts working days inclusively between the two dates, excluding Saturdays,
Sundays, and optional ISO dates in `holidays`. A reversed interval returns a
negative count. Very large spans produce `#LIMIT!`.

**Example:** `=NETWORKDAYS("2026-07-13","2026-07-17",A1:A3)`

### `NETWORKDAYS.INTL`

**Syntax:** `NETWORKDAYS.INTL(start_date, end_date, [weekend], [holidays])`

Counts working days inclusively using a configurable weekend code or
Monday-first seven-character mask. `weekend` defaults to `1`
(Saturday/Sunday). Optional holidays must be strict ISO dates; reversed
intervals return negative counts.

**Example:** `=NETWORKDAYS.INTL("2026-07-13","2026-07-17",1,A1:A3)`

### `WEEKNUM`

**Syntax:** `WEEKNUM(iso_date, [return_type])`

Returns the week number containing the date. Type `1` is the default and starts
weeks on Sunday; type `2` starts Monday. Types `11` through `17` start Monday
through Sunday respectively. Type `21` uses ISO week numbering. Unsupported
types produce `#NUM!`.

**Example:** `=WEEKNUM("2026-07-18",2)`

### `WORKDAY`

**Syntax:** `WORKDAY(start_date, days, [holidays])`

Moves forward or backward by a truncated number of working days, excluding
Saturdays, Sundays, and optional holiday dates. The start date is not counted
when `days` is nonzero; zero returns the start date unchanged. Very large
spans produce `#LIMIT!`.

**Example:** `=WORKDAY("2026-07-17",1,A1:A3)`

### `WORKDAY.INTL`

**Syntax:** `WORKDAY.INTL(start_date, days, [weekend], [holidays])`

Moves by working days using a configurable weekend code or seven-character
mask. `weekend` defaults to `1`. The start date is excluded for a nonzero move,
and optional holiday dates are also skipped.

**Example:** `=WORKDAY.INTL("2026-07-17",1,1,A1:A3)`

### `YEARFRAC`

**Syntax:** `YEARFRAC(start_date, end_date, [basis])`

Returns the signed fraction of a year between two dates. `basis` defaults to
`0` (US 30/360); `1` is actual/actual using the lengths of crossed years, `2`
is actual/360, `3` is actual/365, and `4` is European 30/360. Other basis
values produce `#NUM!`.

**Example:** `=YEARFRAC("2026-01-01","2026-07-01",1)`

## Conversion

### `CONVERT`

**Syntax:** `CONVERT(number, from_unit, to_unit)`

Converts between units in the same supported family. Unit names are
case-insensitive. Length units are `m`, `km`, `cm`, `mm`, `in`, `ft`, `yd`,
and `mi`; mass units are `g`, `kg`, `lb`, and `oz`. Unsupported units or a
length-to-mass conversion produce `#VALUE!`. Formula-cell unit metadata is
descriptive and is not inferred or applied automatically.

**Example:** `=CONVERT(5,"km","mi")`

## Financial

Rates are decimal rates per period: use `0.05` for five percent. Bullpen follows
the usual cash-flow sign convention, so money paid and money received use
opposite signs. In periodic annuity functions, `type` defaults to `0` for
payments at the end of each period; use `1` for payments at the beginning.
Iterative functions use bounded deterministic solvers and return `#NUM!` when
they cannot converge.

### `PV`

**Syntax:** `PV(rate, nper, pmt, [fv], [type])`

Returns the present value of periodic equal payments and an optional future
value. `fv` and `type` default to `0`. A zero rate uses the undiscounted sum;
otherwise payments are adjusted for end- or beginning-of-period timing.

**Example:** `=PV(0.05/12,60,-200,0,0)`

### `FV`

**Syntax:** `FV(rate, nper, pmt, [pv], [type])`

Returns the future value after `nper` periods given equal payments and an
optional present value. `pv` and `type` default to `0`.

**Example:** `=FV(0.05/12,60,-200,-1000,0)`

### `PMT`

**Syntax:** `PMT(rate, nper, pv, [fv], [type])`

Returns the equal payment required per period for a present value and optional
future value. `fv` and `type` default to `0`. A zero-period or otherwise
undefined payment calculation produces a formula error.

**Example:** `=PMT(0.06/12,360,300000,0,0)`

### `NPV`

**Syntax:** `NPV(rate, value1, [value2], ...)`

Returns the net present value of periodic cash flows. The first supplied cash
flow is discounted as period `1`, the next as period `2`, and so on; add an
undiscounted period-zero investment outside the function if needed. Range
arguments are flattened, and blanks are ignored.

**Example:** `=-1000+NPV(0.1,A1:A5)`

### `IRR`

**Syntax:** `IRR(cash_flow1, ...)`

Returns the periodic internal rate of return that makes the period-zero NPV of
the flattened cash flows equal zero. At least one negative and one positive
flow are required. Bullpen uses a fixed initial guess of `0.1`; this form does
not accept a guess argument.

**Example:** `=IRR(-1000,300,400,500)`

### `MIRR`

**Syntax:** `MIRR(cash_flows..., finance_rate, reinvest_rate)`

Returns modified internal rate of return. The final two arguments are the rate
used to finance negative flows and the rate used to reinvest positive flows;
all preceding scalar and range items are flattened as cash flows. At least two
flows, including both signs, are required.

**Example:** `=MIRR(A1:A5,0.08,0.1)`

### `NPER`

**Syntax:** `NPER(rate, payment, present_value, [future_value], [type])`

Returns the number of periods required for the supplied payment and balance
terms. `future_value` and `type` default to `0`. Impossible logarithmic domains,
zero payments where division is required, and other invalid combinations
produce `#NUM!`.

**Example:** `=NPER(0.05/12,-200,10000,0,0)`

### `RATE`

**Syntax:** `RATE(periods, payment, present_value, [future_value], [type], [guess])`

Returns the interest rate per period that balances the annuity terms.
`future_value` and `type` default to `0`, and `guess` defaults to `0.1`.
Non-convergence produces `#NUM!`.

**Example:** `=RATE(60,-200,10000,0,0,0.01)`

### `XIRR`

**Syntax:** `XIRR(cash_flows, dates, [guess])`

Returns an annualized internal rate of return for irregularly dated cash
flows. `cash_flows` and `dates` must have equal nonzero sizes and include both
positive and negative flows. Exponents use actual day offsets from the first
date divided by `365`. `guess` defaults to `0.1`.

**Example:** `=XIRR(A1:A4,B1:B4)`

### `XNPV`

**Syntax:** `XNPV(rate, cash_flows, dates)`

Returns net present value for irregularly dated flows using actual day offsets
from the first date divided by `365`. The cash-flow and date ranges must be
equally sized and, in Bullpen's current contract, must contain at least one
positive and one negative flow.

**Example:** `=XNPV(0.1,A1:A4,B1:B4)`

## Engineering

Base-conversion functions use uppercase output. A positive optional `places`
argument pads output with leading zeroes and cannot truncate it. Binary, octal,
and hexadecimal inputs use fixed signed widths of 10 binary digits, 10 octal
digits (30 bits), and 10 hexadecimal digits (40 bits); full-width values with
the high bit set are interpreted as two's-complement negatives. Decimal target
ranges are therefore:

- binary: `-512` through `511`;
- octal: `-536870912` through `536870911`;
- hexadecimal: `-549755813888` through `549755813887`.

The bitwise functions are separate from those conversion widths. They operate
on unsigned integers from `0` through `2^48 - 1`.

### `BIN2DEC`

**Syntax:** `BIN2DEC(number)`

Parses up to 10 binary digits and returns a decimal integer. A 10-digit value
with its high bit set is interpreted as a negative two's-complement value.

**Example:** `=BIN2DEC("101")`

### `BIN2HEX`

**Syntax:** `BIN2HEX(number, [places])`

Parses a signed-width binary value and returns uppercase hexadecimal text.
`places` may pad a non-negative result up to 10 characters.

**Example:** `=BIN2HEX("101",4)`

### `BIN2OCT`

**Syntax:** `BIN2OCT(number, [places])`

Parses a signed-width binary value and returns octal text. `places` may pad a
non-negative result up to 10 characters.

**Example:** `=BIN2OCT("101",4)`

### `DEC2BIN`

**Syntax:** `DEC2BIN(number, [places])`

Truncates a numeric decimal argument and returns binary text. The value must be
from `-512` through `511`; negative results use the full 10-digit
two's-complement representation.

**Example:** `=DEC2BIN(5,8)`

### `DEC2HEX`

**Syntax:** `DEC2HEX(number, [places])`

Truncates a numeric decimal argument and returns uppercase hexadecimal text.
The value must fit the signed 40-bit conversion range.

**Example:** `=DEC2HEX(255,4)`

### `DEC2OCT`

**Syntax:** `DEC2OCT(number, [places])`

Truncates a numeric decimal argument and returns octal text. The value must fit
the signed 30-bit conversion range.

**Example:** `=DEC2OCT(64,4)`

### `HEX2BIN`

**Syntax:** `HEX2BIN(number, [places])`

Parses up to 10 hexadecimal digits and converts the signed result to binary
text. The decoded value must also fit the binary target range.

**Example:** `=HEX2BIN("F",8)`

### `HEX2DEC`

**Syntax:** `HEX2DEC(number)`

Parses up to 10 hexadecimal digits and returns a decimal integer. A full-width
value with its high bit set is interpreted as signed two's complement.

**Example:** `=HEX2DEC("FF")`

### `HEX2OCT`

**Syntax:** `HEX2OCT(number, [places])`

Parses a signed-width hexadecimal value and returns octal text. The decoded
value must fit the octal target range.

**Example:** `=HEX2OCT("FF",4)`

### `OCT2BIN`

**Syntax:** `OCT2BIN(number, [places])`

Parses up to 10 octal digits and converts the signed result to binary text. The
decoded value must fit the binary target range.

**Example:** `=OCT2BIN("7",8)`

### `OCT2DEC`

**Syntax:** `OCT2DEC(number)`

Parses up to 10 octal digits and returns a decimal integer. A full-width value
with its high bit set is interpreted as signed two's complement.

**Example:** `=OCT2DEC("17")`

### `OCT2HEX`

**Syntax:** `OCT2HEX(number, [places])`

Parses a signed-width octal value and returns uppercase hexadecimal text.

**Example:** `=OCT2HEX("377",4)`

### `BITAND`

**Syntax:** `BITAND(number, number2)`

Returns the bitwise AND of two unsigned 48-bit integers. Fractional, negative,
or out-of-range arguments produce `#NUM!`.

**Example:** `=BITAND(6,3)`

### `BITLSHIFT`

**Syntax:** `BITLSHIFT(number, shift)`

Shifts an unsigned 48-bit integer left by an integer number of bits. A negative
shift performs a right shift. Absolute shifts above `4096` produce `#LIMIT!`;
a result beyond 48 bits produces `#NUM!`.

**Example:** `=BITLSHIFT(3,2)`

### `BITOR`

**Syntax:** `BITOR(number, number2)`

Returns the bitwise OR of two unsigned 48-bit integers. Fractional, negative,
or out-of-range arguments produce `#NUM!`.

**Example:** `=BITOR(6,3)`

### `BITRSHIFT`

**Syntax:** `BITRSHIFT(number, shift)`

Shifts an unsigned 48-bit integer right by an integer number of bits. A
negative shift performs a left shift. Absolute shifts above `4096` produce
`#LIMIT!`, and the result must remain within 48 bits.

**Example:** `=BITRSHIFT(12,2)`

### `BITXOR`

**Syntax:** `BITXOR(number, number2)`

Returns the bitwise exclusive OR of two unsigned 48-bit integers. Fractional,
negative, or out-of-range arguments produce `#NUM!`.

**Example:** `=BITXOR(6,3)`

## Catalog discovery

Agents can retrieve the same catalog, including signatures, categories,
examples, range support, and optional search filtering, through the
`list_formula_functions` MCP tool. The MCP catalog is the machine-readable
source of truth for public availability; this document supplies the
human-readable behavioral detail.
