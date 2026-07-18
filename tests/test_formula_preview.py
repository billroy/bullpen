"""Read-only Quick Calculate coverage for the server formula engine."""

from pathlib import Path
import tempfile

import pytest

from server.app import create_app, socketio


def _event(client, name):
    for event in client.get_received():
        if event["name"] == name:
            return event["args"][0]
    return None


@pytest.fixture
def preview_clients():
    with tempfile.TemporaryDirectory(prefix="bullpen_formula_preview_") as workspace:
        app = create_app(workspace, no_browser=True)
        requester = socketio.test_client(app)
        observer = socketio.test_client(app)
        requester.get_received()
        observer.get_received()
        yield requester, observer, app
        requester.disconnect()
        observer.disconnect()


def _add_value(client, *, col, row, value, name=""):
    client.emit("worker:add", {
        "coord": {"col": col, "row": row},
        "type": "value",
        "fields": {
            "name": name,
            "value": str(value),
            "value_type": "number",
        },
    })
    assert _event(client, "layout:updated") is not None


def _preview(client, source, request_id):
    client.emit("formula:preview", {"source": source, "request_id": request_id})
    payload = _event(client, "formula:previewed")
    assert payload is not None
    assert payload["request_id"] == request_id
    return payload


def test_formula_preview_uses_ranges_names_and_sheet_functions_without_mutation(preview_clients):
    requester, observer, app = preview_clients
    _add_value(requester, col=4, row=44, value=2)
    _add_value(requester, col=23, row=48, value=5)
    _add_value(requester, col=0, row=0, value=0.5, name="tax_rate")
    observer.get_received()

    layout_path = Path(app.config["bp_dir"]) / "layout.json"
    before_layout = layout_path.read_bytes()

    payload = _preview(
        requester,
        "=sum(e45:x49)",
        "exact-range",
    )
    named_payload = _preview(
        requester,
        "=sum(e45:x49)+tax_rate",
        "range-and-name",
    )

    assert payload["ok"] is True
    assert payload["source"] == "=sum(e45:x49)"
    assert payload["expression"] == "sum(e45:x49)"
    assert payload["value"] == 7
    assert payload["result"] == "7"
    assert payload["resolved_value_type"] == "number"
    assert payload["dependencies"] == ["E45", "X49"]
    assert payload["warnings"] == []
    assert payload["volatile"] is False
    assert named_payload["ok"] is True
    assert named_payload["value"] == 7.5
    assert named_payload["dependencies"] == ["E45", "X49", "A1"]
    assert layout_path.read_bytes() == before_layout

    observer_events = observer.get_received()
    assert all(event["name"] != "formula:previewed" for event in observer_events)
    assert all(event["name"] != "layout:updated" for event in observer_events)


def test_formula_preview_has_no_host_cell_but_explicit_coordinates_work(preview_clients):
    requester, observer, app = preview_clients
    _add_value(requester, col=4, row=44, value=3)
    observer.get_received()
    layout_path = Path(app.config["bp_dir"]) / "layout.json"
    before_layout = layout_path.read_bytes()

    no_context = _preview(requester, "=ROW()", "row-without-cell")
    explicit_context = _preview(requester, "=ROW(E45)+COLUMN($E$45)", "row-with-cell")
    anchored_range = _preview(requester, "=SUM($E$45:E$45)", "anchored-range")
    top_level_range = _preview(requester, "=E45:E45", "top-level-range")

    assert no_context["ok"] is False
    assert no_context["error"]["code"] == "#VALUE!"
    assert no_context["error"]["message"] == "ROW requires cell context"
    assert explicit_context["ok"] is True
    assert explicit_context["value"] == 50
    assert anchored_range["ok"] is True
    assert anchored_range["value"] == 3
    assert top_level_range["ok"] is False
    assert top_level_range["error"]["code"] == "#VALUE!"
    assert layout_path.read_bytes() == before_layout


def test_formula_preview_uses_sheet_limits_and_duplicate_name_warnings(preview_clients):
    requester, observer, app = preview_clients
    _add_value(requester, col=0, row=0, value=2, name="Rate")
    _add_value(requester, col=1, row=0, value=3, name="rate")
    observer.get_received()
    layout_path = Path(app.config["bp_dir"]) / "layout.json"
    before_layout = layout_path.read_bytes()

    named = _preview(requester, "=rate", "duplicate-name")
    long_formula = _preview(requester, '=LEN("' + ("x" * 600) + '")', "long-formula")
    missing_equals = _preview(requester, "SUM(A1:B1)", "missing-equals")

    assert named["ok"] is True
    assert named["value"] == 2
    assert named["dependencies"] == ["A1"]
    assert "other matches: B1" in named["warnings"][0]
    assert long_formula["ok"] is True
    assert long_formula["value"] == 600
    assert missing_equals["ok"] is False
    assert missing_equals["error"] == {
        "code": "#PARSE!",
        "message": "Formula must start with =",
    }
    assert layout_path.read_bytes() == before_layout
