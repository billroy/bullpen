import json
from pathlib import Path
import shutil
import subprocess

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
    grid = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert "/components/FormulaHelpCard.js" in index_html
    assert "'formula-help:index'" in component
    assert "socket.emit(requestEvent" in component
    assert "loadBullpenFormulaHelpIndex()" in component
    assert 'v-if="formulaHelpOpen"' in card
    assert '@keydown.f1.prevent.stop="openFormulaHelp"' in card
    assert "@click.stop=\"openFormulaHelp\"" in card
    assert "if (this.formulaHelpOpen) return;" in card
    assert "valueShortcutHelpOpen: false" in grid
    assert "@click.stop=\"openValueShortcutFormulaHelp\"" in grid
    assert "this.openValueShortcutFormulaHelp();" in grid
    assert ":initial-query=\"valueShortcutHelpInitialQuery\"" in grid
    assert "fx Help" in grid
    assert "bullpenFormulaHelpQuery(input)" in component


def test_formula_help_primary_path_is_empty_cell_expression_creation():
    grid = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    editor = grid.split('v-if="valueShortcutEditor"', 1)[1].split(
        'v-if="ghostCell && emptyMenuOpenFor(ghostCell)"', 1
    )[0]
    assert 'ref="valueShortcutInput"' in editor
    assert 'aria-label="Open formula help. Shortcut F1."' in editor
    assert "@click.stop=\"openValueShortcutFormulaHelp\"" in editor
    assert "FormulaHelpCard" in editor

    handler = grid.split("onValueShortcutKeydown(e) {", 1)[1].split(
        "rememberValueShortcutSelection()", 1
    )[0]
    assert "e.key === 'F1'" in handler
    assert "this.openValueShortcutFormulaHelp();" in handler

    close_method = grid.split("closeValueShortcutFormulaHelp() {", 1)[1]
    assert "input.focus?.();" in close_method
    assert "input.setSelectionRange" in close_method


def test_empty_cell_f1_opens_contextual_help_without_mutating_draft():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    grid_path = ROOT / "static" / "components" / "BullpenTab.js"
    help_path = ROOT / "static" / "components" / "FormulaHelpCard.js"
    script = f"""
const fs = require('fs');
const vm = require('vm');
const gridSource = fs.readFileSync({json.dumps(str(grid_path))}, 'utf8');
const helpSource = fs.readFileSync({json.dumps(str(help_path))}, 'utf8');
const context = {{
  console,
  localStorage: {{ getItem: () => null, setItem: () => {{}} }},
  WorkerCard: {{}},
  FormulaHelpCard: {{}},
  window: {{ innerWidth: 1200, innerHeight: 800, setTimeout, clearTimeout }},
}};
vm.createContext(context);
vm.runInContext(helpSource + `
  globalThis.__query = bullpenFormulaHelpQuery({{ value: '=SUM', selectionStart: 4 }});
`, context);
vm.runInContext(gridSource + `
  const draft = {{ text: '=SUM', error: '' }};
  const component = {{
    valueShortcutEditor: draft,
    opened: 0,
    openValueShortcutFormulaHelp() {{ this.opened += 1; }},
  }};
  const event = {{
    key: 'F1',
    prevented: false,
    stopped: false,
    preventDefault() {{ this.prevented = true; }},
    stopPropagation() {{ this.stopped = true; }},
  }};
  BullpenTab.methods.onValueShortcutKeydown.call(component, event);
  globalThis.__result = {{
    draft: component.valueShortcutEditor.text,
    opened: component.opened,
    prevented: event.prevented,
    stopped: event.stopped,
  }};
`, context);
process.stdout.write(JSON.stringify({{ query: context.__query, ...context.__result }}));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload == {
        "query": "SUM",
        "draft": "=SUM",
        "opened": 1,
        "prevented": True,
        "stopped": True,
    }
