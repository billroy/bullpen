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


def test_quick_calculate_uses_server_formula_preview_not_a_second_parser():
    commands = _read("static/commands.js")
    app = _read("static/app.js")
    toolbar = _read("static/components/TopToolbar.js")

    assert "QuickCalculateParser" not in commands
    assert "QUICK_CALCULATE_FUNCTIONS" not in commands
    assert "evaluateQuickCalculate" not in commands
    assert "function requestQuickCalculate(source)" in app
    assert "socket.emit('formula:preview'" in app
    assert "socket.on('formula:previewed', onPreviewed);" in app
    assert ':quick-calculate="requestQuickCalculate"' in app
    assert "await this.quickCalculate(submittedText)" in toolbar


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
  globalThis.__toolbar = TopToolbar;
`, context);
const TopToolbar = context.__toolbar;

(async () => {{
  const emitted = [];
  const requested = [];
  const component = {{
    quickCreateText: '=SUM(E45:X49)',
    quickCalculatePending: false,
    showPalette: true,
    paletteOverlayOpen: true,
    selectedPaletteIndex: 0,
    quickCalculate: async source => {{
      requested.push(source);
      return {{
        ok: true,
        expression: 'SUM(E45:X49)',
        value: 7.5,
        result: '7.5',
        warnings: [],
      }};
    }},
    focusActiveInput() {{ this.focused = true; }},
    closePaletteOverlay: TopToolbar.methods.closePaletteOverlay,
    submitQuickCalculate: TopToolbar.methods.submitQuickCalculate,
    $emit(...args) {{ emitted.push(args); }},
  }};
  Object.defineProperty(component, 'paletteMode', {{
    get() {{ return TopToolbar.computed.paletteMode.call(component); }},
  }});
  await TopToolbar.methods.submitQuickCreate.call(component);

  const errorEmitted = [];
  const errorComponent = {{
    quickCreateText: '=1/0',
    quickCalculatePending: false,
    showPalette: false,
    paletteOverlayOpen: false,
    selectedPaletteIndex: 0,
    quickCalculate: async () => ({{
      ok: false,
      expression: '1/0',
      error: {{ code: '#DIV/0!', message: 'Division by zero' }},
    }}),
    focusActiveInput() {{ this.focused = true; }},
    closePaletteOverlay: TopToolbar.methods.closePaletteOverlay,
    submitQuickCalculate: TopToolbar.methods.submitQuickCalculate,
    $emit(...args) {{ errorEmitted.push(args); }},
  }};
  Object.defineProperty(errorComponent, 'paletteMode', {{
    get() {{ return TopToolbar.computed.paletteMode.call(errorComponent); }},
  }});
  await TopToolbar.methods.submitQuickCreate.call(errorComponent);

  let finishRequest;
  const raceEmitted = [];
  const raceComponent = {{
    quickCreateText: '=SUM(A1:A2)',
    quickCalculatePending: false,
    showPalette: true,
    paletteOverlayOpen: true,
    selectedPaletteIndex: 0,
    quickCalculate: () => new Promise(resolve => {{ finishRequest = resolve; }}),
    focusActiveInput() {{}},
    closePaletteOverlay: TopToolbar.methods.closePaletteOverlay,
    $emit(...args) {{ raceEmitted.push(args); }},
  }};
  const racePromise = TopToolbar.methods.submitQuickCalculate.call(raceComponent);
  raceComponent.quickCreateText = '=SUM(B1:B2)';
  finishRequest({{
    ok: true,
    expression: 'SUM(A1:A2)',
    result: '3',
    warnings: [],
  }});
  await racePromise;

  const disconnectEmitted = [];
  const disconnectComponent = {{
    quickCreateText: '=SUM(A1:B1)',
    quickCalculatePending: false,
    showPalette: false,
    paletteOverlayOpen: false,
    selectedPaletteIndex: 0,
    quickCalculate: async () => {{ throw new Error('Disconnected from Bullpen server'); }},
    focusActiveInput() {{ this.focused = true; }},
    closePaletteOverlay: TopToolbar.methods.closePaletteOverlay,
    $emit(...args) {{ disconnectEmitted.push(args); }},
  }};
  await TopToolbar.methods.submitQuickCalculate.call(disconnectComponent);

  const result = {{
    emitted,
    requested,
    text: component.quickCreateText,
    showPalette: component.showPalette,
    paletteOverlayOpen: component.paletteOverlayOpen,
    errorEmitted,
    errorText: errorComponent.quickCreateText,
    errorShowPalette: errorComponent.showPalette,
    errorFocused: errorComponent.focused === true,
    errorPending: errorComponent.quickCalculatePending,
    raceText: raceComponent.quickCreateText,
    raceOverlayOpen: raceComponent.paletteOverlayOpen,
    raceEmitted,
    disconnectText: disconnectComponent.quickCreateText,
    disconnectPending: disconnectComponent.quickCalculatePending,
    disconnectFocused: disconnectComponent.focused === true,
    disconnectEmitted,
  }};
  process.stdout.write(JSON.stringify(result));
}})().catch(error => {{
  console.error(error);
  process.exitCode = 1;
}});
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["requested"] == ["=SUM(E45:X49)"]
    assert payload["emitted"] == [["toast", "SUM(E45:X49) = 7.5", "success"]]
    assert payload["text"] == ""
    assert payload["showPalette"] is False
    assert payload["paletteOverlayOpen"] is False
    assert payload["errorEmitted"][0][0] == "toast"
    assert payload["errorEmitted"][0][2] == "error"
    assert payload["errorEmitted"][0][1] == "1/0 = #DIV/0! Division by zero"
    assert payload["errorText"] == "=1/0"
    assert payload["errorShowPalette"] is True
    assert payload["errorFocused"] is True
    assert payload["errorPending"] is False
    assert payload["raceText"] == "=SUM(B1:B2)"
    assert payload["raceOverlayOpen"] is True
    assert payload["raceEmitted"] == [["toast", "SUM(A1:A2) = 3", "success"]]
    assert payload["disconnectText"] == "=SUM(A1:B1)"
    assert payload["disconnectPending"] is False
    assert payload["disconnectFocused"] is True
    assert payload["disconnectEmitted"] == [[
        "toast",
        "SUM(A1:B1) = Disconnected from Bullpen server",
        "error",
    ]]
    assert all(call[0] != "quick-create-task" for call in payload["emitted"] + payload["errorEmitted"])
