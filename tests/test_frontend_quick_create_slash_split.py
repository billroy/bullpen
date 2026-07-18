"""Regression checks for slash-splitting in the toolbar quick ticket create."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_commands_split_quick_create_text_splits_at_first_slash():
    text = _read("static/commands.js")
    assert "function splitQuickCreateText(text)" in text
    assert "const slashIdx = raw.indexOf('/');" in text
    assert "title: raw.slice(0, slashIdx).trim()," in text
    assert "description: raw.slice(slashIdx + 1).trim()," in text


def test_app_quick_create_accepts_payload_with_description():
    text = _read("static/app.js")
    assert "function quickCreateTask(payload)" in text
    assert "const title = typeof payload === 'string' ? payload.trim() : (payload?.title || '').trim();" in text
    assert "const description = typeof payload === 'string' ? '' : (payload?.description || '').trim();" in text
    assert "pendingQuickCreates.push({ title, description });" in text
    assert "socket.emit('task:create', _wsData({ title, type: 'task', priority: 'normal', tags: [], description }));" in text


def test_quick_create_input_clears_only_after_create_ack():
    app = _read("static/app.js")
    toolbar = _read("static/components/TopToolbar.js")
    assert "const quickCreateClearToken = ref(0);" in app
    assert "quickCreateClearToken.value++;" in app
    assert ':quick-create-clear-token="quickCreateClearToken"' in app
    assert "quickCreateClearToken() {" in toolbar
    assert "this.quickCreateText = '';" in toolbar


def test_toolbar_quick_create_placeholder_mentions_ticket_and_description():
    text = _read("static/components/TopToolbar.js")
    assert 'placeholder="New ticket / description, or > commands"' in text


def test_quick_calculate_evaluator_returns_results_and_errors():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "commands.js"))}, 'utf8');
const context = {{ window: {{}}, console }};
vm.createContext(context);
vm.runInContext(source + `
  const calculate = window.BullpenCommands.evaluateQuickCalculate;
  globalThis.__results = {{
    precedence: calculate('=2+3*4'),
    exponent: calculate('=2^3^2'),
    functionCall: calculate('=sqrt(16)+max(2, 5)'),
    division: calculate('=2/0'),
    blockedIdentifier: calculate('=window.alert(1)'),
  }};
`, context);
process.stdout.write(JSON.stringify(context.__results));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["precedence"] == {"ok": True, "expression": "2+3*4", "value": 14, "result": "14"}
    assert payload["exponent"] == {"ok": True, "expression": "2^3^2", "value": 512, "result": "512"}
    assert payload["functionCall"] == {"ok": True, "expression": "sqrt(16)+max(2, 5)", "value": 9, "result": "9"}
    assert payload["division"]["ok"] is False
    assert payload["division"]["expression"] == "2/0"
    assert "Division by zero" in payload["division"]["error"]
    assert payload["blockedIdentifier"]["ok"] is False
    assert "Unknown constant" in payload["blockedIdentifier"]["error"]


def test_toolbar_quick_calculate_submits_to_toast_not_ticket_create():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const commandsSource = fs.readFileSync({json.dumps(str(ROOT / "static" / "commands.js"))}, 'utf8');
const toolbarSource = fs.readFileSync({json.dumps(str(ROOT / "static" / "components" / "TopToolbar.js"))}, 'utf8');
const context = {{ window: {{}}, console }};
vm.createContext(context);
vm.runInContext(commandsSource + '\\n' + toolbarSource + `
  const emitted = [];
  const component = {{
    quickCreateText: '=2+2*3',
    showPalette: true,
    paletteOverlayOpen: true,
    selectedPaletteIndex: 0,
    focusActiveInput() {{ this.focused = true; }},
    closePaletteOverlay: TopToolbar.methods.closePaletteOverlay,
    submitQuickCalculate: TopToolbar.methods.submitQuickCalculate,
    $emit(...args) {{ emitted.push(args); }},
  }};
  Object.defineProperty(component, 'paletteMode', {{
    get() {{ return TopToolbar.computed.paletteMode.call(component); }},
  }});
  TopToolbar.methods.submitQuickCreate.call(component);

  const errorEmitted = [];
  const errorComponent = {{
    quickCreateText: '=2/0',
    showPalette: false,
    paletteOverlayOpen: false,
    selectedPaletteIndex: 0,
    focusActiveInput() {{ this.focused = true; }},
    closePaletteOverlay: TopToolbar.methods.closePaletteOverlay,
    submitQuickCalculate: TopToolbar.methods.submitQuickCalculate,
    $emit(...args) {{ errorEmitted.push(args); }},
  }};
  Object.defineProperty(errorComponent, 'paletteMode', {{
    get() {{ return TopToolbar.computed.paletteMode.call(errorComponent); }},
  }});
  TopToolbar.methods.submitQuickCreate.call(errorComponent);

  globalThis.__result = {{
    emitted,
    text: component.quickCreateText,
    showPalette: component.showPalette,
    paletteOverlayOpen: component.paletteOverlayOpen,
    errorEmitted,
    errorText: errorComponent.quickCreateText,
    errorShowPalette: errorComponent.showPalette,
    errorFocused: errorComponent.focused === true,
  }};
`, context);
process.stdout.write(JSON.stringify(context.__result));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["emitted"] == [["toast", "2+2*3 = 8", "success"]]
    assert payload["text"] == ""
    assert payload["showPalette"] is False
    assert payload["paletteOverlayOpen"] is False
    assert payload["errorEmitted"][0][0] == "toast"
    assert payload["errorEmitted"][0][2] == "error"
    assert payload["errorEmitted"][0][1].startswith("2/0 = Division by zero")
    assert payload["errorText"] == "=2/0"
    assert payload["errorShowPalette"] is True
    assert payload["errorFocused"] is True
    assert all(call[0] != "quick-create-task" for call in payload["emitted"] + payload["errorEmitted"])
