from datetime import datetime, timezone

import pytest

from server.formulas import (
    FormulaError,
    coerce_formula_result,
    evaluate_formula,
    normalize_formula,
    normalize_formula_state,
    parse_formula,
)


def _slots():
    return [
        {
            "type": "value", "name": "tax_rate", "value": 2,
            "value_type": "number", "resolved_value_type": "number",
            "row": 0, "col": 0,
        },
        {
            "type": "value", "name": "Tax Rate", "value": 3,
            "value_type": "number", "resolved_value_type": "number",
            "row": 1, "col": 0,
        },
        {
            "type": "value", "name": "Output", "value": 0,
            "value_type": "auto", "resolved_value_type": "number",
            "row": 0, "col": 1,
        },
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("=1+2*3", 7),
        ("=(1+2)*3", 9),
        ("=2^3^2", 512),
        ("=-2^2", 4),
        ("=5%2", 1),
        ('="a" & "b"', "ab"),
        ("=1<2", True),
        ('="ALPHA"="alpha"', True),
    ],
)
def test_scalar_operators_and_precedence(source, expected):
    assert evaluate_formula(source, []).value == expected


def test_coordinate_and_named_references_record_dependencies_and_warnings():
    coord = evaluate_formula("=$A$1 + tax_rate", _slots(), current_index=2)
    named = evaluate_formula("=[Tax Rate]", _slots(), current_index=2)

    assert coord.value == 4
    assert coord.dependencies == ["A1"]
    assert named.value == 3
    assert named.dependencies == ["A2"]
    assert named.warnings == []


def test_duplicate_names_resolve_row_major_with_warning():
    slots = _slots()
    slots[0]["name"] = "duplicate"
    slots[1]["name"] = "Duplicate"

    result = evaluate_formula("=duplicate", slots, current_index=2)

    assert result.value == 2
    assert result.dependencies == ["A1"]
    assert "other matches: A2" in result.warnings[0]


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("=missing", "#NAME?"),
        ("=Z99", "#REF!"),
        ("=B1", "#CYCLE!"),
        ("=1/0", "#DIV/0!"),
        ('=1+"x"', "#VALUE!"),
        ("=UNKNOWN(1)", "#NAME?"),
        ("=SUM(A1:A2)", "#PARSE!"),
    ],
)
def test_safe_errors(source, code):
    with pytest.raises(FormulaError) as caught:
        evaluate_formula(source, _slots(), current_index=2)
    assert caught.value.code == code


def test_short_circuit_functions_do_not_evaluate_unused_errors():
    assert evaluate_formula("=IF(FALSE,1/0,7)", []).value == 7
    assert evaluate_formula("=IFERROR(1/0,9)", []).value == 9
    assert evaluate_formula("=ISERROR(1/0)", []).value is True
    assert evaluate_formula("=AND(FALSE,1/0)", []).value is False
    assert evaluate_formula("=OR(TRUE,1/0)", []).value is True


def test_core_scalar_functions():
    assert evaluate_formula("=ABS(-2)", []).value == 2
    assert evaluate_formula("=ROUND(1.25,1)", []).value == 1.3
    assert evaluate_formula("=ROUNDUP(-1.21,1)", []).value == -1.3
    assert evaluate_formula("=ROUNDDOWN(-1.29,1)", []).value == -1.2
    assert evaluate_formula("=MOD(7,4)", []).value == 3
    assert evaluate_formula('=ISTEXT("x")', []).value is True
    assert evaluate_formula("=ISNUMBER(2)", []).value is True


def test_volatile_functions_use_injected_server_clock():
    now = datetime(2026, 7, 16, 15, 30, tzinfo=timezone.utc)
    today = evaluate_formula("=TODAY()", [], now=now)
    current = evaluate_formula("=NOW()", [], now=now)

    assert today.value == "2026-07-16"
    assert current.value == "2026-07-16T15:30:00Z"
    assert today.volatile is True
    assert current.volatile is True


def test_formula_normalization_and_state_are_bounded_and_stable():
    assert normalize_formula(" A1+1 ") == {"source": "=A1+1", "version": 1}
    state = normalize_formula_state({"status": "wat", "warnings": ["x"], "dependencies": ["A1"]})
    assert state["status"] == "pending"
    assert state["warnings"] == ["x"]
    assert state["dependencies"] == ["A1"]
    parse_formula("=1")


def test_result_policy_rejects_wrong_number_and_canonicalizes_boolean():
    assert coerce_formula_result(True, "auto") == ("true", "string")
    assert coerce_formula_result(3, "string") == ("3", "string")
    with pytest.raises(FormulaError) as caught:
        coerce_formula_result("three", "number")
    assert caught.value.code == "#VALUE!"
