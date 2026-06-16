"""Tests for value worker helpers."""

from server.values import (
    append_value_history,
    col_label,
    coord_to_cell_ref,
    find_value_by_ref,
    normalize_format,
    normalize_unit,
    normalize_value_history,
    normalize_value_payload,
    parse_cell_ref,
    row_label,
    unit_labels,
)
from server.templates import render_value_template
from server.templates import render_context_value_template


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


def test_value_history_entries_normalize_values_and_timestamps():
    slot = {"value": "42", "value_type": "auto", "save_history": True, "updated_at": "2026-06-16T12:00:00Z"}

    append_value_history(slot)
    slot["value"] = "007"
    slot["updated_at"] = "2026-06-16T12:01:00Z"
    append_value_history(slot)

    assert slot["history"] == [
        {
            "value": 42,
            "value_type": "auto",
            "resolved_value_type": "number",
            "updated_at": "2026-06-16T12:00:00Z",
        },
        {
            "value": "007",
            "value_type": "auto",
            "resolved_value_type": "string",
            "updated_at": "2026-06-16T12:01:00Z",
        },
    ]


def test_value_history_append_noops_when_history_is_disabled():
    slot = {"value": "42", "value_type": "auto", "save_history": False, "updated_at": "2026-06-16T12:00:00Z"}

    assert append_value_history(slot) is None
    assert "history" not in slot


def test_value_history_normalization_discards_invalid_entries():
    assert normalize_value_history([
        {"value": "5", "value_type": "number", "updated_at": "t1"},
        "bad",
        {"value": "x", "value_type": "bogus"},
    ]) == [
        {
            "value": 5,
            "value_type": "number",
            "resolved_value_type": "number",
            "updated_at": "t1",
        },
        {
            "value": "x",
            "value_type": "auto",
            "resolved_value_type": "string",
            "updated_at": "",
        },
    ]


def test_value_format_normalizes_known_kinds_and_bounds():
    assert normalize_format({"kind": "currency", "places": 99, "symbol": "USDollars"}) == {
        "kind": "currency",
        "places": 10,
        "symbol": "USDollar",
    }
    assert normalize_format({"kind": "mystery"}) == {"kind": "auto"}


def test_value_units_normalize_common_aliases_and_custom_text():
    assert normalize_unit("f") == "fahrenheit"
    assert unit_labels("fahrenheit") == {
        "unit": "fahrenheit",
        "abbreviation": "°F",
        "name": "degree Fahrenheit",
    }
    assert unit_labels("widgets") == {
        "unit": "widgets",
        "abbreviation": "widgets",
        "name": "widgets",
    }


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


def test_context_value_template_renders_context_first_then_values():
    slots = [
        {"type": "value", "row": 0, "col": 0, "name": "direction", "value": "west"},
        {"type": "value", "row": 0, "col": 1, "name": "ticket.title", "value": "shadowed"},
    ]
    context = {
        "ticket": {"title": "Real ticket"},
        "worker": {"name": "Notifier"},
    }

    rendered = render_context_value_template(
        "say {direction} for {ticket.title} via {worker.name}",
        context,
        slots,
        max_len=200,
        context_label="notification",
    )

    assert rendered.text == "say west for Real ticket via Notifier"
    assert rendered.warnings == []
