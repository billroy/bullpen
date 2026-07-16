"""Machine-readable metadata for the formula evaluator's public functions."""

from __future__ import annotations

from typing import Any


def _function(
    name: str,
    category: str,
    signature: str,
    summary: str,
    example: str,
    *,
    accepts_ranges: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "category": category,
        "signature": signature,
        "summary": summary,
        "examples": [example],
        "accepts_ranges": accepts_ranges,
    }


FORMULA_FUNCTIONS = (
    _function("IF", "Logic and tests", "IF(condition, value_if_true, [value_if_false])", "Returns one value when a condition is true and another when it is false.", "=IF(TRUE,1,0)"),
    _function("IFERROR", "Logic and tests", "IFERROR(value, fallback)", "Returns a fallback when evaluating value produces a formula error.", "=IFERROR(1/0,0)"),
    _function("ISERROR", "Logic and tests", "ISERROR(value)", "Tests whether evaluating a value produces a formula error.", "=ISERROR(1/0)"),
    _function("AND", "Logic and tests", "AND(value1, [value2], ...)", "Returns true when every argument is truthy.", "=AND(TRUE,1)"),
    _function("OR", "Logic and tests", "OR(value1, [value2], ...)", "Returns true when any argument is truthy.", "=OR(FALSE,1)"),
    _function("NOT", "Logic and tests", "NOT(value)", "Reverses the truth value of its argument.", "=NOT(FALSE)"),
    _function("ISNUMBER", "Logic and tests", "ISNUMBER(value)", "Tests whether a value is numeric.", "=ISNUMBER(2)"),
    _function("ISTEXT", "Logic and tests", "ISTEXT(value)", "Tests whether a value is text.", '=ISTEXT("text")'),
    _function("ISBLANK", "Logic and tests", "ISBLANK(value)", "Tests whether a value is blank.", '=ISBLANK("")'),
    _function("SUM", "Math and aggregation", "SUM(value1, [value2], ...)", "Adds numeric values and ranges; ignores blanks and text.", "=SUM(1,2,3)", accepts_ranges=True),
    _function("AVERAGE", "Math and aggregation", "AVERAGE(value1, [value2], ...)", "Returns the arithmetic mean of numeric values and ranges.", "=AVERAGE(1,2,3)", accepts_ranges=True),
    _function("MIN", "Math and aggregation", "MIN(value1, [value2], ...)", "Returns the smallest numeric value.", "=MIN(1,2,3)", accepts_ranges=True),
    _function("MAX", "Math and aggregation", "MAX(value1, [value2], ...)", "Returns the largest numeric value.", "=MAX(1,2,3)", accepts_ranges=True),
    _function("COUNT", "Math and aggregation", "COUNT(value1, [value2], ...)", "Counts numeric values in arguments and ranges.", "=COUNT(1,2,\"text\")", accepts_ranges=True),
    _function("ABS", "Math and aggregation", "ABS(number)", "Returns the absolute value of a number.", "=ABS(-2)"),
    _function("ROUND", "Math and aggregation", "ROUND(number, [digits])", "Rounds a number to the requested decimal digits.", "=ROUND(1.25,1)"),
    _function("ROUNDUP", "Math and aggregation", "ROUNDUP(number, [digits])", "Rounds a number away from zero.", "=ROUNDUP(1.21,1)"),
    _function("ROUNDDOWN", "Math and aggregation", "ROUNDDOWN(number, [digits])", "Rounds a number toward zero.", "=ROUNDDOWN(1.29,1)"),
    _function("MOD", "Math and aggregation", "MOD(number, divisor)", "Returns the remainder after division.", "=MOD(7,4)"),
    _function("DELTA", "Math and aggregation", "DELTA(number1, [number2])", "Returns 1 when two numbers are equal, otherwise 0.", "=DELTA(2,2)"),
    _function("GESTEP", "Math and aggregation", "GESTEP(number, [step])", "Returns 1 when number is at least step, otherwise 0.", "=GESTEP(3,2)"),
    _function("CONCAT", "Text", "CONCAT(value1, [value2], ...)", "Joins values and ranges without a delimiter.", '=CONCAT("a","b")', accepts_ranges=True),
    _function("TEXTJOIN", "Text", "TEXTJOIN(delimiter, ignore_empty, text1, [text2], ...)", "Joins values and ranges with a delimiter.", '=TEXTJOIN("-",TRUE,"a","b")', accepts_ranges=True),
    _function("LEFT", "Text", "LEFT(text, [count])", "Returns characters from the start of text.", '=LEFT("abcd",2)'),
    _function("RIGHT", "Text", "RIGHT(text, [count])", "Returns characters from the end of text.", '=RIGHT("abcd",2)'),
    _function("MID", "Text", "MID(text, start, count)", "Returns characters from the middle of text using a one-based start.", '=MID("abcd",2,2)'),
    _function("LEN", "Text", "LEN(text)", "Returns the number of characters in text.", '=LEN("abcd")'),
    _function("TRIM", "Text", "TRIM(text)", "Trims outer whitespace and collapses internal whitespace.", '=TRIM(" a  b ")'),
    _function("UPPER", "Text", "UPPER(text)", "Converts text to uppercase.", '=UPPER("text")'),
    _function("LOWER", "Text", "LOWER(text)", "Converts text to lowercase.", '=LOWER("TEXT")'),
    _function("SUBSTITUTE", "Text", "SUBSTITUTE(text, old_text, new_text, [occurrence])", "Replaces matching text, optionally at one occurrence.", '=SUBSTITUTE("a-b-a","a","x")'),
    _function("DATE", "Date and time", "DATE(year, month, day)", "Builds a strict ISO date.", "=DATE(2026,7,16)"),
    _function("YEAR", "Date and time", "YEAR(date)", "Returns the year from a strict ISO date.", '=YEAR("2026-07-16")'),
    _function("MONTH", "Date and time", "MONTH(date)", "Returns the month from a strict ISO date.", '=MONTH("2026-07-16")'),
    _function("DAY", "Date and time", "DAY(date)", "Returns the day from a strict ISO date.", '=DAY("2026-07-16")'),
    _function("DAYS", "Date and time", "DAYS(end_date, start_date)", "Returns the number of days between two strict ISO dates.", '=DAYS("2026-07-16","2026-07-01")'),
    _function("NOW", "Date and time", "NOW()", "Returns the current server UTC timestamp.", "=NOW()"),
    _function("TODAY", "Date and time", "TODAY()", "Returns the current server date.", "=TODAY()"),
    _function("CONVERT", "Conversion", "CONVERT(number, from_unit, to_unit)", "Converts supported length or mass units.", '=CONVERT(1,"km","m")'),
    _function("PV", "Financial", "PV(rate, nper, pmt, [fv], [type])", "Returns the present value of periodic cash flows.", "=PV(0,2,10,100)"),
    _function("FV", "Financial", "FV(rate, nper, pmt, [pv], [type])", "Returns the future value of periodic cash flows.", "=FV(0,2,10,100)"),
    _function("PMT", "Financial", "PMT(rate, nper, pv, [fv], [type])", "Returns the periodic payment for a loan or annuity.", "=PMT(0,2,100)"),
    _function("NPV", "Financial", "NPV(rate, value1, [value2], ...)", "Returns net present value for periodic cash flows.", "=NPV(0.1,100,100)", accepts_ranges=True),
)

FORMULA_FUNCTIONS_BY_NAME = {item["name"]: item for item in FORMULA_FUNCTIONS}
FORMULA_FUNCTION_NAMES = frozenset(FORMULA_FUNCTIONS_BY_NAME)


def list_formula_functions(query: object = "") -> list[dict[str, Any]]:
    """Return catalog entries filtered by name, category, signature, or summary."""
    needle = " ".join(str(query or "").casefold().split())
    entries = FORMULA_FUNCTIONS
    if needle:
        entries = tuple(
            item for item in entries
            if needle in " ".join(
                str(item.get(key) or "") for key in ("name", "category", "signature", "summary")
            ).casefold()
        )
    return [dict(item) for item in entries]
