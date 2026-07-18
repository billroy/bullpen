from pathlib import Path

from server.app import create_app, socketio
from server.formula_functions import FORMULA_FUNCTION_NAMES
from server.formula_help import formula_function_help, formula_help_index, reference_function_names


ROOT = Path(__file__).resolve().parents[1]


def test_formula_help_index_is_compact_and_covers_public_catalog():
    index = formula_help_index()

    assert len(index) == 173
    assert {item["name"] for item in index} == FORMULA_FUNCTION_NAMES
    assert set(index[0]) == {"name", "category", "signature", "summary"}
    assert all("examples" not in item and "documentation" not in item for item in index)


def test_function_reference_covers_every_public_function():
    assert reference_function_names() == FORMULA_FUNCTION_NAMES


def test_formula_help_detail_uses_long_form_reference():
    detail = formula_function_help("sum")

    assert detail["name"] == "SUM"
    assert detail["signature"] == "SUM(value1, [value2], ...)"
    assert "Adds all numeric scalar and range items" in detail["documentation"]
    assert detail["examples"] == ["=SUM(A1:A10,25)"]
    assert detail["accepts_ranges"] is True
    assert formula_function_help("not-a-function") is None


def _received_payload(client, event_name):
    matches = [event for event in client.get_received() if event["name"] == event_name]
    assert matches
    return matches[-1]["args"][0]


def test_formula_help_socket_events_separate_index_from_detail(tmp_workspace):
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("formula-help:index", {"request_id": "index-1"})
    index_payload = _received_payload(client, "formula-help:indexed")
    assert index_payload["request_id"] == "index-1"
    assert len(index_payload["functions"]) == 173
    assert "documentation" not in index_payload["functions"][0]

    client.emit("formula-help:function", {"request_id": "detail-1", "name": "SUM"})
    detail_payload = _received_payload(client, "formula-help:function-loaded")
    assert detail_payload["request_id"] == "detail-1"
    assert detail_payload["function"]["name"] == "SUM"
    assert detail_payload["function"]["documentation"]

    client.emit("formula-help:function", {"request_id": "detail-2", "name": "NOPE"})
    error_payload = _received_payload(client, "formula-help:error")
    assert error_payload == {
        "request_id": "detail-2",
        "error": "Unknown formula function",
    }
    client.disconnect()


def test_formula_help_frontend_is_explicit_and_lazy():
    index_html = (ROOT / "static" / "index.html").read_text()
    component = (ROOT / "static" / "components" / "FormulaHelpCard.js").read_text()
    card = (ROOT / "static" / "components" / "WorkerCard.js").read_text()

    assert "/components/FormulaHelpCard.js" in index_html
    assert "'formula-help:index'" in component
    assert "socket.emit(requestEvent" in component
    assert "loadBullpenFormulaHelpIndex()" in component
    assert 'v-if="formulaHelpOpen"' in card
    assert '@keydown.f1.prevent.stop="openFormulaHelp"' in card
    assert "@click.stop=\"openFormulaHelp\"" in card
    assert "if (this.formulaHelpOpen) return;" in card
