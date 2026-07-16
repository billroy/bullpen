import math

import pytest

from server.formula_functions import APPROVED_FORMULA_FUNCTIONS, P0_FORMULA_FUNCTION_NAMES
from server.formulas import FormulaError, evaluate_formula


def _grid(values, *, cols=3):
    return [
        {
            "type": "value",
            "value": value,
            "value_type": "auto",
            "resolved_value_type": "number" if isinstance(value, (int, float)) else "string",
            "row": index // cols,
            "col": index % cols,
        }
        for index, value in enumerate(values)
    ]


def _value(source, slots=None, **kwargs):
    return evaluate_formula(source, slots or [], **kwargs).value


def test_approved_catalog_contains_exact_frozen_p0_and_p1_surface():
    names = {entry["name"] for entry in APPROVED_FORMULA_FUNCTIONS}
    assert len(names) == 130
    assert len(P0_FORMULA_FUNCTION_NAMES) == 47
    assert sum(entry["priority"] == "P0" for entry in APPROVED_FORMULA_FUNCTIONS) == 47
    assert sum(entry["priority"] == "P1" for entry in APPROVED_FORMULA_FUNCTIONS) == 83
    assert {"SQRT", "LOG", "EXP", "XLOOKUP", "XIRR"} <= names
    assert {
        "BIN2DEC", "BIN2HEX", "BIN2OCT", "DEC2BIN", "DEC2HEX", "DEC2OCT",
        "HEX2BIN", "HEX2DEC", "HEX2OCT", "OCT2BIN", "OCT2DEC", "OCT2HEX",
        "BITAND", "BITOR", "BITXOR", "BITLSHIFT", "BITRSHIFT",
    } <= names


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("=SQRT(81)", 9),
        ("=LOG(8,2)", 3),
        ("=LN(EXP(2))", 2),
        ("=POWER(2,10)", 1024),
        ("=CEILING.MATH(-4.2)", -4),
        ("=FLOOR.MATH(-4.2)", -5),
        ("=INT(-4.2)", -5),
        ("=TRUNC(-4.2)", -4),
        ("=QUOTIENT(-7,2)", -3),
        ("=COMBIN(5,2)", 10),
        ("=GCD(24,18)", 6),
        ("=LCM(4,6)", 12),
        ("=SUMSQ(2,3)", 13),
    ],
)
def test_math_rituals(source, expected):
    assert _value(source) == pytest.approx(expected)


def test_trigonometry_and_domain_errors_are_bounded():
    assert _value("=SIN(PI()/2)") == pytest.approx(1)
    assert _value("=DEGREES(PI())") == pytest.approx(180)
    assert _value("=ATAN2(1,1)") == pytest.approx(math.pi / 4)
    for source in ("=SQRT(-1)", "=LN(0)", "=ACOS(2)"):
        with pytest.raises(FormulaError) as caught:
            _value(source)
        assert caught.value.code == "#NUM!"


def test_logic_information_and_lazy_error_functions():
    assert _value("=IFNA(NA(),7)") == 7
    assert _value('=IFS(FALSE,"bad",TRUE,"good")') == "good"
    assert _value('=SWITCH("b","a",1,"b",2,0)') == 2
    assert _value("=ISNA(NA())") is True
    assert _value("=ISERR(1/0)") is True
    assert _value("=ISERR(NA())") is False
    assert _value("=XOR(TRUE,FALSE,TRUE)") is False
    assert _value("=TYPE(TRUE)") == 4
    assert _value('=N("text")') == 0


def test_range_criteria_statistics_and_lookup_rituals():
    slots = _grid([1, 10, "a", 2, 20, "b", 3, 30, "c"])
    assert _value('=COUNTIF(A1:A3,">1")', slots, cols=3) == 2
    assert _value('=SUMIF(A1:A3,">1",B1:B3)', slots, cols=3) == 50
    assert _value('=AVERAGEIFS(B1:B3,A1:A3,">1")', slots, cols=3) == 25
    assert _value('=MAXIFS(B1:B3,A1:A3,"<=2")', slots, cols=3) == 20
    assert _value("=SUMPRODUCT(A1:A3,B1:B3)", slots, cols=3) == 140
    assert _value("=MEDIAN(B1:B3)", slots, cols=3) == 20
    assert _value("=PERCENTILE.INC(B1:B3,0.25)", slots, cols=3) == 15
    assert _value("=STDEV.P(B1:B3)", slots, cols=3) == pytest.approx(8.1649658093)
    assert _value("=INDEX(A1:C3,2,2)", slots, cols=3) == 20
    assert _value("=MATCH(2,A1:A3,0)", slots, cols=3) == 2
    assert _value('=XLOOKUP(2,A1:A3,C1:C3,"missing")', slots, cols=3) == "b"
    assert _value("=ROWS(A1:C3)+COLUMNS(A1:C3)", slots, cols=3) == 6
    assert _value("=ROW()", slots, current_index=4, cols=3) == 2
    assert _value("=COLUMN()", slots, current_index=4, cols=3) == 2


def test_text_parsing_formatting_and_extraction_rituals():
    assert _value('=CLEAN("a"&CHAR(9)&"b")') == "ab"
    assert _value('=FIND("B","aBc")') == 2
    assert _value('=SEARCH("b","aBc")') == 2
    assert _value('=REPLACE("abcd",2,2,"X")') == "aXd"
    assert _value('=TEXTBEFORE("a:b:c",":",-1)') == "a:b"
    assert _value('=TEXTAFTER("a:b:c",":",2)') == "c"
    assert _value('=NUMBERVALUE("1.234,5",",",".")') == 1234.5
    assert _value('=TEXT(1234.5,"#,##0.00")') == "1,234.50"
    assert _value('=EXACT("a","A")') is False
    assert _value('=UNICODE(UNICHAR(9731))') == 9731


def test_iso_date_calendar_and_workday_rituals():
    assert _value('=EDATE("2026-01-31",1)') == "2026-02-28"
    assert _value('=EOMONTH("2024-01-10",1)') == "2024-02-29"
    assert _value("=TIME(25,0,0)") == "01:00:00"
    assert _value('=HOUR("2026-07-16T12:34:56Z")') == 12
    assert _value('=WEEKDAY("2026-07-13",2)') == 1
    assert _value('=ISOWEEKNUM("2026-01-01")') == 1
    assert _value('=NETWORKDAYS("2026-07-13","2026-07-17")') == 5
    assert _value('=WORKDAY("2026-07-17",1)') == "2026-07-20"
    assert _value('=DATEDIF("2024-01-01","2026-07-01","M")') == 30
    assert _value('=YEARFRAC("2026-01-01","2027-01-01",3)') == 1


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('=BIN2DEC("1111111111")', -1),
        ("=DEC2BIN(5,8)", "00000101"),
        ('=HEX2DEC("FF")', 255),
        ("=DEC2HEX(-1)", "FFFFFFFFFF"),
        ('=OCT2BIN("7",4)', "0111"),
        ("=BITAND(6,3)", 2),
        ("=BITOR(6,3)", 7),
        ("=BITXOR(6,3)", 5),
        ("=BITLSHIFT(3,2)", 12),
        ("=BITRSHIFT(12,2)", 3),
        ("=BITLSHIFT(12,-2)", 3),
    ],
)
def test_base_conversion_and_bitwise_rituals(source, expected):
    assert _value(source) == expected


def test_financial_rituals_and_dated_cash_flows():
    assert _value("=IRR(-100,60,60)") == pytest.approx(0.1306623863)
    assert _value("=MIRR(-100,60,60,0.1,0.12)") == pytest.approx(0.1278297744)
    assert _value("=NPER(0,-10,100)") == 10
    assert _value("=RATE(10,-12,100)") == pytest.approx(0.034601538)
    slots = _grid([-100, "2026-01-01", 0, 110, "2027-01-01", 0], cols=3)
    assert _value("=XNPV(0.1,A1:A2,B1:B2)", slots, cols=3) == pytest.approx(0)
    assert _value("=XIRR(A1:A2,B1:B2)", slots, cols=3) == pytest.approx(0.1)


def test_new_functions_reject_shape_overflow_and_convergence_failures():
    slots = _grid([1, 10, 0, 2, 20, 0], cols=3)
    cases = [
        ('=SUMIFS(A1:A2,B1:B1,">0")', "#VALUE!"),
        ("=BITLSHIFT(281474976710655,1)", "#NUM!"),
        ("=DEC2BIN(512)", "#NUM!"),
        ("=IRR(1,2,3)", "#NUM!"),
    ]
    for source, code in cases:
        with pytest.raises(FormulaError) as caught:
            _value(source, slots, cols=3)
        assert caught.value.code == code
