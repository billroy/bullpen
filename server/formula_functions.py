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


CORE_FORMULA_FUNCTIONS = (
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


def _approved(name: str, category: str, signature: str, example: str, *, ranges: bool = False) -> dict[str, Any]:
    return _function(name, category, signature, f"Bullpen {name} formula function.", example, accepts_ranges=ranges)


APPROVED_FORMULA_FUNCTIONS = (
    # P0 date and time.
    _approved("DATEVALUE", "Date and time", "DATEVALUE(iso_date)", '=DATEVALUE("2026-07-16")'),
    _approved("EDATE", "Date and time", "EDATE(iso_date, months)", '=EDATE("2026-01-31",1)'),
    _approved("EOMONTH", "Date and time", "EOMONTH(iso_date, months)", '=EOMONTH("2026-01-10",1)'),
    _approved("HOUR", "Date and time", "HOUR(iso_time)", '=HOUR("12:34:56")'),
    _approved("MINUTE", "Date and time", "MINUTE(iso_time)", '=MINUTE("12:34:56")'),
    _approved("SECOND", "Date and time", "SECOND(iso_time)", '=SECOND("12:34:56")'),
    _approved("TIME", "Date and time", "TIME(hour, minute, second)", "=TIME(12,34,56)"),
    _approved("TIMEVALUE", "Date and time", "TIMEVALUE(iso_time)", '=TIMEVALUE("12:34:56")'),
    _approved("WEEKDAY", "Date and time", "WEEKDAY(iso_date, [return_type])", '=WEEKDAY("2026-07-16",2)'),
    # P0 information, logic, and lookup.
    _approved("ISNA", "Logic and tests", "ISNA(value)", "=ISNA(NA())"),
    _approved("TYPE", "Logic and tests", "TYPE(value)", "=TYPE(1)"),
    _approved("IFNA", "Logic and tests", "IFNA(value, fallback)", "=IFNA(NA(),0)"),
    _approved("IFS", "Logic and tests", "IFS(condition1, value1, ...)", '=IFS(FALSE,"no",TRUE,"yes")'),
    _approved("SWITCH", "Logic and tests", "SWITCH(expression, value1, result1, ..., [default])", '=SWITCH(2,1,"one",2,"two")'),
    _approved("INDEX", "Lookup and reference", "INDEX(range, row, [column])", "=INDEX(7,1)", ranges=True),
    _approved("MATCH", "Lookup and reference", "MATCH(value, range, [match_type])", "=MATCH(2,2,0)", ranges=True),
    _approved("XLOOKUP", "Lookup and reference", "XLOOKUP(value, lookup_range, return_range, [not_found], [match_mode], [search_mode])", "=XLOOKUP(2,2,7)", ranges=True),
    # P0 math and aggregation.
    _approved("CEILING.MATH", "Math and aggregation", "CEILING.MATH(number, [significance], [mode])", "=CEILING.MATH(4.2)"),
    _approved("EXP", "Math and aggregation", "EXP(number)", "=EXP(1)"),
    _approved("FLOOR.MATH", "Math and aggregation", "FLOOR.MATH(number, [significance], [mode])", "=FLOOR.MATH(4.8)"),
    _approved("INT", "Math and aggregation", "INT(number)", "=INT(4.8)"),
    _approved("LN", "Math and aggregation", "LN(number)", "=LN(2)"),
    _approved("LOG", "Math and aggregation", "LOG(number, [base])", "=LOG(8,2)"),
    _approved("LOG10", "Math and aggregation", "LOG10(number)", "=LOG10(100)"),
    _approved("PI", "Math and aggregation", "PI()", "=PI()"),
    _approved("POWER", "Math and aggregation", "POWER(number, power)", "=POWER(2,3)"),
    _approved("PRODUCT", "Math and aggregation", "PRODUCT(value1, ...)", "=PRODUCT(2,3)", ranges=True),
    _approved("SIGN", "Math and aggregation", "SIGN(number)", "=SIGN(-2)"),
    _approved("SQRT", "Math and aggregation", "SQRT(number)", "=SQRT(4)"),
    _approved("SUMIF", "Math and aggregation", "SUMIF(criteria_range, criterion, [sum_range])", '=SUMIF(2,">1",3)', ranges=True),
    _approved("SUMIFS", "Math and aggregation", "SUMIFS(sum_range, criteria_range1, criterion1, ...)", '=SUMIFS(3,2,">1")', ranges=True),
    _approved("SUMPRODUCT", "Math and aggregation", "SUMPRODUCT(range1, ...)", "=SUMPRODUCT(2,3)", ranges=True),
    _approved("TRUNC", "Math and aggregation", "TRUNC(number)", "=TRUNC(4.8)"),
    # P0 statistics and text.
    _approved("COUNTA", "Statistical", "COUNTA(value1, ...)", '=COUNTA(1,"x")', ranges=True),
    _approved("COUNTBLANK", "Statistical", "COUNTBLANK(value1, ...)", '=COUNTBLANK("")', ranges=True),
    _approved("COUNTIF", "Statistical", "COUNTIF(criteria_range, criterion)", '=COUNTIF(2,">1")', ranges=True),
    _approved("COUNTIFS", "Statistical", "COUNTIFS(criteria_range1, criterion1, ...)", '=COUNTIFS(2,">1")', ranges=True),
    _approved("MEDIAN", "Statistical", "MEDIAN(value1, ...)", "=MEDIAN(1,2,3)", ranges=True),
    _approved("CLEAN", "Text", "CLEAN(text)", '=CLEAN("a")'),
    _approved("FIND", "Text", "FIND(find_text, within_text, [start])", '=FIND("b","abc")'),
    _approved("NUMBERVALUE", "Text", "NUMBERVALUE(text, [decimal_separator], [group_separator])", '=NUMBERVALUE("1,234.5")'),
    _approved("REPLACE", "Text", "REPLACE(text, start, count, replacement)", '=REPLACE("abc",2,1,"x")'),
    _approved("SEARCH", "Text", "SEARCH(find_text, within_text, [start])", '=SEARCH("B","abc")'),
    _approved("TEXT", "Text", "TEXT(value, format)", '=TEXT(12.3,"0.00")'),
    _approved("TEXTAFTER", "Text", "TEXTAFTER(text, delimiter, [instance])", '=TEXTAFTER("a:b",":")'),
    _approved("TEXTBEFORE", "Text", "TEXTBEFORE(text, delimiter, [instance])", '=TEXTBEFORE("a:b",":")'),
    _approved("VALUE", "Text", "VALUE(text)", '=VALUE("12.5")'),
    # P1 dates.
    _approved("DATEDIF", "Date and time", "DATEDIF(start_date, end_date, unit)", '=DATEDIF("2025-01-01","2026-01-01","Y")'),
    _approved("ISOWEEKNUM", "Date and time", "ISOWEEKNUM(iso_date)", '=ISOWEEKNUM("2026-07-16")'),
    _approved("NETWORKDAYS", "Date and time", "NETWORKDAYS(start_date, end_date, [holidays])", '=NETWORKDAYS("2026-07-13","2026-07-17")', ranges=True),
    _approved("NETWORKDAYS.INTL", "Date and time", "NETWORKDAYS.INTL(start_date, end_date, [weekend], [holidays])", '=NETWORKDAYS.INTL("2026-07-13","2026-07-17",1)', ranges=True),
    _approved("WEEKNUM", "Date and time", "WEEKNUM(iso_date, [return_type])", '=WEEKNUM("2026-07-16",2)'),
    _approved("WORKDAY", "Date and time", "WORKDAY(start_date, days, [holidays])", '=WORKDAY("2026-07-17",1)', ranges=True),
    _approved("WORKDAY.INTL", "Date and time", "WORKDAY.INTL(start_date, days, [weekend], [holidays])", '=WORKDAY.INTL("2026-07-17",1,1)', ranges=True),
    _approved("YEARFRAC", "Date and time", "YEARFRAC(start_date, end_date, [basis])", '=YEARFRAC("2026-01-01","2026-07-01",1)'),
    # P1 information, logic, and lookup.
    _approved("ISERR", "Logic and tests", "ISERR(value)", "=ISERR(1/0)"),
    _approved("ISEVEN", "Logic and tests", "ISEVEN(number)", "=ISEVEN(2)"),
    _approved("ISLOGICAL", "Logic and tests", "ISLOGICAL(value)", "=ISLOGICAL(TRUE)"),
    _approved("ISODD", "Logic and tests", "ISODD(number)", "=ISODD(3)"),
    _approved("N", "Logic and tests", "N(value)", "=N(TRUE)"),
    _approved("NA", "Logic and tests", "NA()", "=NA()"),
    _approved("XOR", "Logic and tests", "XOR(value1, ...)", "=XOR(TRUE,FALSE)"),
    _approved("CHOOSE", "Lookup and reference", "CHOOSE(index, value1, ...)", '=CHOOSE(2,"a","b")'),
    _approved("COLUMN", "Lookup and reference", "COLUMN([reference])", "=COLUMN()"),
    _approved("COLUMNS", "Lookup and reference", "COLUMNS(range)", "=COLUMNS(1)", ranges=True),
    _approved("ROW", "Lookup and reference", "ROW([reference])", "=ROW()"),
    _approved("ROWS", "Lookup and reference", "ROWS(range)", "=ROWS(1)", ranges=True),
    _approved("XMATCH", "Lookup and reference", "XMATCH(value, range, [match_mode], [search_mode])", "=XMATCH(2,2)", ranges=True),
    # P1 math and trigonometry.
    *tuple(_approved(name, "Math and trigonometry", f"{name}(number)", f"={name}({0.5 if name == 'ATANH' else 1})") for name in
           ("ACOS", "ACOSH", "ASIN", "ASINH", "ATAN", "ATANH", "COS", "COSH", "DEGREES", "RADIANS", "SIN", "SINH", "TAN", "TANH")),
    _approved("ATAN2", "Math and trigonometry", "ATAN2(x, y)", "=ATAN2(1,1)"),
    _approved("COMBIN", "Math and trigonometry", "COMBIN(number, chosen)", "=COMBIN(4,2)"),
    _approved("FACT", "Math and trigonometry", "FACT(number)", "=FACT(5)"),
    _approved("GCD", "Math and trigonometry", "GCD(number1, ...)", "=GCD(8,12)"),
    _approved("LCM", "Math and trigonometry", "LCM(number1, ...)", "=LCM(4,6)"),
    _approved("QUOTIENT", "Math and trigonometry", "QUOTIENT(numerator, denominator)", "=QUOTIENT(7,2)"),
    _approved("SUMSQ", "Math and trigonometry", "SUMSQ(value1, ...)", "=SUMSQ(2,3)", ranges=True),
    # P1 statistics.
    _approved("AVERAGEIF", "Statistical", "AVERAGEIF(criteria_range, criterion, [average_range])", '=AVERAGEIF(2,">1",4)', ranges=True),
    _approved("AVERAGEIFS", "Statistical", "AVERAGEIFS(average_range, criteria_range1, criterion1, ...)", '=AVERAGEIFS(4,2,">1")', ranges=True),
    _approved("LARGE", "Statistical", "LARGE(range, rank)", "=LARGE(2,1)", ranges=True),
    _approved("MAXIFS", "Statistical", "MAXIFS(max_range, criteria_range1, criterion1, ...)", '=MAXIFS(4,2,">1")', ranges=True),
    _approved("MINIFS", "Statistical", "MINIFS(min_range, criteria_range1, criterion1, ...)", '=MINIFS(4,2,">1")', ranges=True),
    _approved("PERCENTILE.INC", "Statistical", "PERCENTILE.INC(range, k)", "=PERCENTILE.INC(2,0.5)", ranges=True),
    _approved("QUARTILE.INC", "Statistical", "QUARTILE.INC(range, quartile)", "=QUARTILE.INC(2,2)", ranges=True),
    _approved("RANK.EQ", "Statistical", "RANK.EQ(number, range, [order])", "=RANK.EQ(2,2)", ranges=True),
    _approved("SMALL", "Statistical", "SMALL(range, rank)", "=SMALL(2,1)", ranges=True),
    _approved("STDEV.P", "Statistical", "STDEV.P(range)", "=STDEV.P(2)", ranges=True),
    _approved("STDEV.S", "Statistical", "STDEV.S(value1, value2, ...)", "=STDEV.S(1,2)", ranges=True),
    # P1 text.
    _approved("CHAR", "Text", "CHAR(code)", "=CHAR(65)"),
    _approved("CODE", "Text", "CODE(text)", '=CODE("A")'),
    _approved("EXACT", "Text", "EXACT(text1, text2)", '=EXACT("a","a")'),
    _approved("PROPER", "Text", "PROPER(text)", '=PROPER("agent work")'),
    _approved("REPT", "Text", "REPT(text, count)", '=REPT("x",2)'),
    _approved("UNICODE", "Text", "UNICODE(text)", '=UNICODE("A")'),
    _approved("UNICHAR", "Text", "UNICHAR(code)", "=UNICHAR(9731)"),
    # P1 financial.
    _approved("IRR", "Financial", "IRR(cash_flow1, ...)", "=IRR(-100,60,60)", ranges=True),
    _approved("MIRR", "Financial", "MIRR(cash_flows..., finance_rate, reinvest_rate)", "=MIRR(-100,60,60,0.1,0.12)", ranges=True),
    _approved("NPER", "Financial", "NPER(rate, payment, present_value, [future_value], [type])", "=NPER(0,-10,100)"),
    _approved("RATE", "Financial", "RATE(periods, payment, present_value, [future_value], [type], [guess])", "=RATE(10,-12,100)"),
    _approved("XIRR", "Financial", "XIRR(cash_flows, dates, [guess])", "=XIRR(A1:A3,B1:B3)", ranges=True),
    _approved("XNPV", "Financial", "XNPV(rate, cash_flows, dates)", "=XNPV(0.1,A1:A3,B1:B3)", ranges=True),
    # P1 engineering.
    *tuple(_approved(name, "Engineering", f"{name}(number, [places])" if not name.endswith("DEC") else f"{name}(number)", f"={name}({example})")
           for name, example in (("BIN2DEC", '"101"'),("BIN2HEX", '"101"'),("BIN2OCT", '"101"'),
                                 ("DEC2BIN", "5"),("DEC2HEX", "15"),("DEC2OCT", "8"),
                                 ("HEX2BIN", '"F"'),("HEX2DEC", '"F"'),("HEX2OCT", '"F"'),
                                 ("OCT2BIN", '"7"'),("OCT2DEC", '"7"'),("OCT2HEX", '"7"'))),
    *tuple(_approved(name, "Engineering", f"{name}(number, {'shift' if 'SHIFT' in name else 'number2'})", f"={name}({left},{right})")
           for name, left, right in (("BITAND",6,3),("BITLSHIFT",3,2),("BITOR",6,3),("BITRSHIFT",12,2),("BITXOR",6,3))),
)


P0_FORMULA_FUNCTION_NAMES = frozenset({
    "DATEVALUE", "EDATE", "EOMONTH", "HOUR", "MINUTE", "SECOND", "TIME", "TIMEVALUE", "WEEKDAY",
    "ISNA", "TYPE", "IFNA", "IFS", "SWITCH", "INDEX", "MATCH", "XLOOKUP",
    "CEILING.MATH", "EXP", "FLOOR.MATH", "INT", "LN", "LOG", "LOG10", "PI", "POWER", "PRODUCT",
    "SIGN", "SQRT", "SUMIF", "SUMIFS", "SUMPRODUCT", "TRUNC", "COUNTA", "COUNTBLANK", "COUNTIF",
    "COUNTIFS", "MEDIAN", "CLEAN", "FIND", "NUMBERVALUE", "REPLACE", "SEARCH", "TEXT", "TEXTAFTER",
    "TEXTBEFORE", "VALUE",
})
APPROVED_FORMULA_FUNCTIONS = tuple({
    **item,
    "priority": "P0" if item["name"] in P0_FORMULA_FUNCTION_NAMES else "P1",
} for item in APPROVED_FORMULA_FUNCTIONS)


FORMULA_FUNCTIONS = CORE_FORMULA_FUNCTIONS + APPROVED_FORMULA_FUNCTIONS

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
