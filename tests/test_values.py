"""Tests for value worker helpers."""

from server.values import (
    col_label,
    coord_to_cell_ref,
    find_value_by_ref,
    normalize_format,
    normalize_value_payload,
    parse_cell_ref,
    row_label,
)
from server.templates import render_value_template


def test_cell_ref_helpers_match_spreadsheet_coordinates():
    assert col_label(0) == "A"
    assert col_label(25) == "Z"
    assert col_label(26) == "AA"
    assert row_label(0) == "1"
    assert coord_to_cell_ref({"col": 27, "row": 4}) == "AB5"
    assert parse_cell_ref(" AB 5 ") == {"col": 27, "row": 4}
    assert parse_cell_ref("A0") is None
    assert coord_to_cell_ref({"col": -1, "row": 0}) == ""


def test_value_payload_auto_detects_plain_numbers_without_erasing_strings():
    assert normalize_value_payload("42") == {
        "value": 42,
        "value_type": "auto",
        "resolved_value_type": "number",
    }
    assert normalize_value_payload("42.5")["value"] == 42.5
    assert normalize_value_payload("00123") == {
        "value": "00123",
        "value_type": "auto",
        "resolved_value_type": "string",
    }
    assert normalize_value_payload("007", "string") == {
        "value": "007",
        "value_type": "string",
        "resolved_value_type": "string",
    }
    assert normalize_value_payload("nope", "number") == {
        "value": 0,
        "value_type": "number",
        "resolved_value_type": "number",
    }


def test_value_format_normalizes_known_kinds_and_bounds():
    assert normalize_format({"kind": "currency", "places": 99, "symbol": "USDollars"}) == {
        "kind": "currency",
        "places": 10,
        "symbol": "USDollar",
    }
    assert normalize_format({"kind": "mystery"}) == {"kind": "auto"}


def test_find_value_by_ref_prefers_cell_reference_then_name_with_ambiguity_flag():
    slots = [
        {"type": "value", "row": 0, "col": 0, "name": "Build", "value": 1},
        {"type": "marker", "row": 0, "col": 1, "name": "Not a value"},
        {"type": "value", "row": 4, "col": 27, "name": "Build", "value": 2},
    ]

    by_cell = find_value_by_ref(slots, "AB5")
    assert by_cell["index"] == 2
    assert by_cell["ambiguous"] is False

    by_name = find_value_by_ref(slots, "build")
    assert by_name["index"] == 0
    assert by_name["ambiguous"] is True

    assert find_value_by_ref(slots, "missing") is None


def test_value_template_renders_raw_values_and_warns_for_missing_or_duplicate_names():
    slots = [
        {"type": "value", "row": 0, "col": 0, "name": "branch", "value": "release/2026"},
        {"type": "value", "row": 1, "col": 0, "name": "branch", "value": "main"},
        {"type": "value", "row": 0, "col": 1, "name": "", "value": 42},
    ]

    rendered = render_value_template("deploy {branch} build {B1} missing {nope}", slots, context_label="command")

    assert rendered.text == "deploy release/2026 build 42 missing {nope}"
    assert any("Duplicate value name matched A1" in warning for warning in rendered.warnings)
    assert any("value 'nope' not found" in warning for warning in rendered.warnings)
