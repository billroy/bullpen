"""Source-level and behavior checks for frontend event sound wiring."""

import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_value_update_sound_is_registered():
    audio = (ROOT / "static" / "audio.js").read_text()
    sounds = (ROOT / "static" / "event-sounds.js").read_text()

    assert "playValueUpdate()" in audio
    assert "valueUpdated: true" in sounds
    assert "_valueSnapshots: new Map()" in sounds
    assert "diffValues(layout)" in sounds
    assert "playValueUpdate" in sounds
    assert "Value updated" in sounds


def test_workspace_pause_gates_ambient_audio():
    app = (ROOT / "static" / "app.js").read_text()
    audio = (ROOT / "static" / "audio.js").read_text()

    assert "const automationPaused = ws.config?.worker_automation_paused === true;" in app
    assert "window.ambientAudio.muteAmbient();" in app
    assert "window.ambientAudio.unmuteAmbient();" in app
    assert "muteAmbient()" in audio
    assert "unmuteAmbient()" in audio
    assert "if (this._ambientMuted) return;" in audio
    assert "_setWorkspaceAutomationPaused(activeWorkspaceId.value, true);" in app
    assert "_setWorkspaceAutomationPaused(activeWorkspaceId.value, false);" in app
    assert "_setKnownWorkspacesAutomationPaused(true);" in app
    assert "_setKnownWorkspacesAutomationPaused(false);" in app


def test_value_update_sound_fires_only_for_known_value_changes():
    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "event-sounds.js"))}, 'utf8');
const handlers = {{}};
const calls = [];
const socket = {{ on(name, fn) {{ handlers[name] = fn; }} }};
const context = {{
  window: {{}},
  localStorage: {{ getItem: () => null, setItem: () => {{}} }},
  setTimeout,
  clearTimeout,
  Date,
  JSON,
}};
context.window.ambientAudio = {{
  _duckAmbient: () => calls.push('duck'),
  playValueUpdate: () => calls.push('value'),
  playStart: () => calls.push('start'),
}};
vm.createContext(context);
vm.runInContext(source, context);
context.window.EventSounds.init(socket);
handlers['state:init']({{
  layout: {{ slots: [{{ type: 'value', value: '1', value_type: 'number', resolved_value_type: 'number' }}] }},
  tasks: [],
}});
context.window.EventSounds._ready = true;
handlers['layout:updated']({{
  slots: [{{ type: 'value', value: '1', value_type: 'number', resolved_value_type: 'number', state: 'idle' }}],
}});
handlers['layout:updated']({{
  slots: [
    {{ type: 'value', value: '1', value_type: 'number', resolved_value_type: 'number', state: 'idle' }},
    {{ type: 'value', value: 'new', value_type: 'string', resolved_value_type: 'string', state: 'idle' }},
  ],
}});
handlers['layout:updated']({{
  slots: [{{ type: 'value', value: '2', value_type: 'number', resolved_value_type: 'number', state: 'idle' }}],
}});
process.stdout.write(JSON.stringify(calls));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["duck", "value"]
