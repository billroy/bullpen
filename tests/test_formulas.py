from datetime import datetime, timezone
import subprocess
import sys

import pytest

from server.formula_functions import FORMULA_FUNCTIONS, FORMULA_FUNCTION_NAMES
from server.formulas import (
    FormulaError,
    coerce_formula_result,
    evaluate_formula,
    normalize_formula,
    normalize_formula_state,
    parse_formula,
    recalculate_layout,
    is_formula_stale,
    translate_formula_source,
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


@pytest.mark.parametrize(
    ("source", "source_coord", "destination_coord", "expected"),
    [
        (
            '=sum(c36:c37)+$C36+C$36+$C$36&"C36:C37"',
            {"col": 2, "row": 37},
            {"col": 3, "row": 39},
            '=sum(D38:D39)+$C38+D$36+$C$36&"C36:C37"',
        ),
        ("=$c36+c$36+$c$36", {"col": 2, "row": 37}, {"col": 3, "row": 38}, "=$c37+D$36+$c$36"),
        ("=[C36]&\"A1\"", {"col": 2, "row": 37}, {"col": 3, "row": 38}, "=[C36]&\"A1\""),
        ("=A1", {"col": 1, "row": 1}, {"col": 0, "row": 0}, "=#REF!"),
        ("=SUM(A1:B2)", {"col": 1, "row": 1}, {"col": 0, "row": 1}, "=SUM(#REF!)"),
    ],
)
def test_formula_translation_preserves_source_and_applies_mixed_reference_rules(
    source, source_coord, destination_coord, expected
):
    assert translate_formula_source(
        source,
        source_coord=source_coord,
        destination_coord=destination_coord,
    ) == expected


def test_formula_translation_noop_is_byte_exact():
    source = ' =sum( c36 : c37 ) & " punctuation: A1! " '
    assert translate_formula_source(
        source,
        source_coord={"col": 2, "row": 37},
        destination_coord={"col": 2, "row": 37},
    ) == source


def test_structural_ref_token_parses_and_evaluates_as_ref_error():
    with pytest.raises(FormulaError) as caught:
        evaluate_formula("=SUM(#REF!)", [])
    assert caught.value.code == "#REF!"


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


def test_ranges_and_aggregate_functions_include_values_and_ignore_blanks():
    slots = _slots()
    result = evaluate_formula("=SUM(A1:B2)", slots, current_index=2)
    assert result.value == 5
    assert result.dependencies == ["A1", "B1", "A2"]
    assert evaluate_formula("=AVERAGE(A1:A2)", slots).value == 2.5
    assert evaluate_formula("=MIN(A1:A2)", slots).value == 2
    assert evaluate_formula("=MAX(A1:A2)", slots).value == 3
    assert evaluate_formula("=COUNT(A1:B2)", slots).value == 3


def test_first_cut_string_date_finance_and_engineering_functions():
    assert evaluate_formula('=CONCAT("a","b")', []).value == "ab"
    assert evaluate_formula('=TEXTJOIN("-",TRUE,"a","","b")', []).value == "a-b"
    assert evaluate_formula('=LEFT("abcd",2)&RIGHT("abcd",1)', []).value == "abd"
    assert evaluate_formula('=MID("abcd",2,2)', []).value == "bc"
    assert evaluate_formula('=LEN(TRIM(" a  b "))', []).value == 3
    assert evaluate_formula('=UPPER("a")&LOWER("B")', []).value == "Ab"
    assert evaluate_formula('=SUBSTITUTE("a-b-a","a","x")', []).value == "x-b-x"
    assert evaluate_formula('=SUBSTITUTE("ab","","x",1)', []).value == "xab"
    assert evaluate_formula('=SUBSTITUTE("ab","","x",3)', []).value == "abx"
    assert evaluate_formula('=SUBSTITUTE("ab","","x",4)', []).value == "ab"
    assert evaluate_formula("=YEAR(DATE(2026,7,16))", []).value == 2026
    assert evaluate_formula('=DAYS("2026-07-16","2026-07-01")', []).value == 15
    assert evaluate_formula("=DELTA(2,2)+GESTEP(3,2)", []).value == 2
    assert evaluate_formula('=CONVERT(1,"km","m")', []).value == 1000
    assert round(evaluate_formula("=NPV(0.1,100,100)", []).value, 6) == round(100 / 1.1 + 100 / 1.21, 6)
    assert evaluate_formula("=FV(0,2,10,100)", []).value == -120


def test_volatile_functions_use_injected_server_clock():
    now = datetime(2026, 7, 16, 15, 30, tzinfo=timezone.utc)
    today = evaluate_formula("=TODAY()", [], now=now)
    current = evaluate_formula("=NOW()", [], now=now)

    assert today.value == "2026-07-16"
    assert current.value == "2026-07-16T15:30:00Z"
    assert today.volatile is True
    assert current.volatile is True


def test_volatile_functions_honor_injected_iana_timezone():
    now = datetime(2026, 7, 17, 2, 0, tzinfo=timezone.utc)

    assert evaluate_formula("=TODAY()", [], now=now, timezone_name="America/New_York").value == "2026-07-16"
    assert (
        evaluate_formula("=NOW()", [], now=now, timezone_name="America/New_York").value
        == "2026-07-16T22:00:00-04:00"
    )


def test_public_function_catalog_examples_are_supported_by_evaluator():
    assert len(FORMULA_FUNCTION_NAMES) == len(FORMULA_FUNCTIONS)
    values = [-100, "2026-01-01", 60, "2027-01-01", 60, "2028-01-01"]
    slots = [
        {"type": "value", "value": value, "row": index // 2, "col": index % 2}
        for index, value in enumerate(values)
    ]
    for entry in FORMULA_FUNCTIONS:
        if entry["name"] == "NA":
            with pytest.raises(FormulaError) as caught:
                evaluate_formula(entry["examples"][0], slots, current_index=0, cols=2)
            assert caught.value.code == "#N/A"
        else:
            result = evaluate_formula(entry["examples"][0], slots, current_index=0, cols=2)
            assert result is not None, entry["name"]


def test_volatile_staleness_is_derived_without_mutating_formula_state():
    now = datetime(2026, 7, 16, 15, 30, tzinfo=timezone.utc)
    recent = {"formula": {"source": "=NOW()"}, "formula_state": {"volatile": True, "calculated_at": "2026-07-16T15:29:30Z"}}
    old = {"formula": {"source": "=NOW()"}, "formula_state": {"volatile": True, "calculated_at": "2026-07-16T15:28:00Z"}}
    yesterday = {"formula": {"source": "=TODAY()"}, "formula_state": {"volatile": True, "calculated_at": "2026-07-15T23:59:00Z"}}
    assert is_formula_stale(recent, now=now) is False
    assert is_formula_stale(old, now=now) is True
    assert is_formula_stale(yesterday, now=now) is True


def test_volatile_staleness_accepts_formula_whitespace():
    now = datetime(2026, 7, 16, 15, 30, tzinfo=timezone.utc)
    slot = {
        "formula": {"source": "=NOW ()"},
        "formula_state": {
            "volatile": True,
            "calculated_at": "2026-07-16T15:28:00Z",
        },
    }

    assert is_formula_stale(slot, now=now) is True


@pytest.mark.parametrize(
    "source",
    [
        "=" + ("9" * 5000),
        "=2^1000000000",
        '=REPT("x",1000000000)',
        "=BITLSHIFT(1,1000000000)",
        "=POWER(2,1000000000)",
        "=ROUND(1,1000000000)",
        "=FV(1,1000000000,1)",
    ],
)
def test_adversarial_formula_inputs_fail_with_limit_errors(source):
    with pytest.raises(FormulaError) as caught:
        evaluate_formula(source, [])

    assert caught.value.code == "#LIMIT!"


def test_adversarial_formulas_complete_inside_a_hard_process_timeout():
    script = """
from server.formulas import FormulaError, evaluate_formula
sources = [
    "=" + ("9" * 5000),
    "=2^1000000000",
    '=REPT("x",1000000000)',
    "=BITLSHIFT(1,1000000000)",
    "=ROUND(1,1000000000)",
    "=FV(1,1000000000,1)",
]
for source in sources:
    try:
        evaluate_formula(source, [])
    except FormulaError as exc:
        assert exc.code == "#LIMIT!"
    else:
        raise AssertionError(source)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ('=SUBSTITUTE("a","","b",1)', None),
        ("=PMT(0,0,1)", "#DIV/0!"),
        ("=NPV(-1,1)", "#DIV/0!"),
        ("=FV(1,1000000,1)", "#LIMIT!"),
        ('=EDATE("2026-01-01",1000000000)', "#VALUE!"),
    ],
)
def test_public_functions_never_leak_host_language_exceptions(source, code):
    if code is None:
        assert evaluate_formula(source, []).value == "ba"
        return
    with pytest.raises(FormulaError) as caught:
        evaluate_formula(source, [])
    assert caught.value.code == code


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


def test_recalculation_generation_updates_dependency_chain_once_in_order():
    layout = {"slots": [
        {"type": "value", "name": "Input", "value": 3, "value_type": "number", "resolved_value_type": "number", "row": 0, "col": 0},
        {"type": "value", "name": "Double", "value": 0, "value_type": "auto", "resolved_value_type": "number", "row": 0, "col": 1, "formula": {"source": "=A1*2", "version": 1}, "save_history": True},
        {"type": "value", "name": "PlusOne", "value": 0, "value_type": "auto", "resolved_value_type": "number", "row": 0, "col": 2, "formula": {"source": "=B1+1", "version": 1}, "save_history": True},
    ]}

    result = recalculate_layout(layout, root_indices={0}, calculated_at="2026-07-16T12:00:00Z")

    assert result["evaluated_count"] == 2
    assert result["changed_count"] == 2
    assert result["error_count"] == 0
    assert [item["index"] for item in result["changed"]] == [1, 2]
    assert layout["slots"][1]["value"] == 6
    assert layout["slots"][2]["value"] == 7
    assert layout["slots"][1]["history"][-1]["value"] == 6


def test_recalculation_passes_sparse_cell_coordinates_to_row_and_column():
    layout = {"slots": [
        None,
        {
            "type": "value",
            "name": "Sparse",
            "value": 0,
            "value_type": "number",
            "resolved_value_type": "number",
            "row": 31,
            "col": 8,
            "formula": {"source": "=ROW()*100+COLUMN()", "version": 1},
        },
    ]}

    result = recalculate_layout(
        layout,
        root_indices=None,
        cols=4,
        calculated_at="2026-07-16T12:00:00Z",
    )

    assert result["error_count"] == 0
    assert layout["slots"][1]["value"] == 3209


def test_recalculation_marks_cycle_and_downstream_error_without_losing_values():
    layout = {"slots": [
        {"type": "value", "name": "A", "value": 10, "value_type": "auto", "resolved_value_type": "number", "row": 0, "col": 0, "formula": {"source": "=B1", "version": 1}},
        {"type": "value", "name": "B", "value": 20, "value_type": "auto", "resolved_value_type": "number", "row": 0, "col": 1, "formula": {"source": "=A1", "version": 1}},
        {"type": "value", "name": "C", "value": 30, "value_type": "auto", "resolved_value_type": "number", "row": 0, "col": 2, "formula": {"source": "=A1+1", "version": 1}},
    ]}

    result = recalculate_layout(layout, root_indices=None, calculated_at="2026-07-16T12:00:00Z")

    assert result["changed_count"] == 0
    assert result["error_count"] == 3
    assert layout["slots"][0]["value"] == 10
    assert layout["slots"][1]["value"] == 20
    assert layout["slots"][2]["value"] == 30
    assert layout["slots"][0]["formula_state"]["error_code"] == "#CYCLE!"
    assert layout["slots"][1]["formula_state"]["error_code"] == "#CYCLE!"
    assert layout["slots"][2]["formula_state"]["error_code"] == "#CYCLE!"


def test_recalculation_handles_dependency_chains_beyond_python_recursion_depth():
    slots = []
    for row in range(1500):
        source = "=1" if row == 0 else f"=A{row}+1"
        slots.append({
            "type": "value",
            "value": 0,
            "value_type": "number",
            "resolved_value_type": "number",
            "row": row,
            "col": 0,
            "formula": {"source": source, "version": 1},
        })
    layout = {"slots": slots}

    result = recalculate_layout(
        layout,
        root_indices=None,
        calculated_at="2026-07-16T12:00:00Z",
        record_history=False,
    )

    assert result["error_count"] == 0
    assert result["evaluated_count"] == 1500
    assert layout["slots"][-1]["value"] == 1500


def test_recalculation_only_touches_transitive_dependents_of_root():
    layout = {"slots": [
        {"type": "value", "value": 2, "value_type": "number", "resolved_value_type": "number", "row": 0, "col": 0},
        {"type": "value", "value": 5, "value_type": "number", "resolved_value_type": "number", "row": 1, "col": 0},
        {"type": "value", "value": 0, "value_type": "auto", "resolved_value_type": "number", "row": 0, "col": 1, "formula": {"source": "=A1*2", "version": 1}},
        {"type": "value", "value": 99, "value_type": "auto", "resolved_value_type": "number", "row": 1, "col": 1, "formula": {"source": "=A2*2", "version": 1}},
    ]}

    result = recalculate_layout(layout, root_indices={0}, calculated_at="2026-07-16T12:00:00Z")

    assert result["affected_indices"] == [2]
    assert layout["slots"][2]["value"] == 4
    assert layout["slots"][3]["value"] == 99


def test_generation_reference_budget_never_leaves_unanalysed_dependents_stale(monkeypatch):
    monkeypatch.setattr("server.formulas.FORMULA_MAX_GENERATION_REFERENCES", 1)
    layout = {"slots": [
        {
            "type": "value", "value": 2, "value_type": "number",
            "resolved_value_type": "number", "row": 0, "col": 0,
        },
        {
            "type": "value", "value": 10, "value_type": "auto",
            "resolved_value_type": "number", "row": 0, "col": 1,
            "formula": {"source": "=A1*2", "version": 1},
        },
        {
            "type": "value", "value": 999, "value_type": "auto",
            "resolved_value_type": "number", "row": 0, "col": 2,
            "formula": {"source": "=A1*3", "version": 1},
        },
    ]}

    result = recalculate_layout(
        layout,
        root_indices={0},
        calculated_at="2026-07-17T00:00:00Z",
    )

    assert result["affected_indices"] == [1, 2]
    assert result["changed_count"] == 1
    assert result["error_count"] == 1
    assert layout["slots"][1]["value"] == 4
    assert layout["slots"][2]["value"] == 999
    assert layout["slots"][2]["formula_state"]["error_code"] == "#LIMIT!"


def test_raw_function_domain_error_isolated_to_affected_formula():
    layout = {"slots": [
        {
            "type": "value", "value": 2, "value_type": "number",
            "resolved_value_type": "number", "row": 0, "col": 0,
        },
        {
            "type": "value", "value": 10, "value_type": "auto",
            "resolved_value_type": "number", "row": 0, "col": 1,
            "formula": {"source": "=PMT(0,0,A1)", "version": 1},
        },
        {
            "type": "value", "value": 0, "value_type": "auto",
            "resolved_value_type": "number", "row": 0, "col": 2,
            "formula": {"source": "=A1*2", "version": 1},
        },
    ]}

    result = recalculate_layout(
        layout,
        root_indices={0},
        calculated_at="2026-07-17T00:00:00Z",
    )

    assert result["error_count"] == 1
    assert result["changed_count"] == 1
    assert layout["slots"][1]["value"] == 10
    assert layout["slots"][1]["formula_state"]["error_code"] == "#DIV/0!"
    assert layout["slots"][2]["value"] == 4
