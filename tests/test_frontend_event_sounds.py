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


def test_alarm_notification_sounds_are_wired_through_frontend():
    audio = (ROOT / "static" / "audio.js").read_text()
    runtime = (ROOT / "static" / "notification-worker.js").read_text()
    modal = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text()

    expected = {
        "klaxon": ("Klaxon", "playKlaxon"),
        "siren": ("Siren", "playSiren"),
        "pulsed_siren": ("Pulsed siren", "playPulsedSiren"),
        "euro_siren": ("Euro siren", "playEuroSiren"),
        "air_raid": ("Air raid", "playAirRaid"),
        "evacuation": ("Evacuation", "playEvacuation"),
    }

    for effect, (label, method) in expected.items():
        assert f"{effect}: '{method}'" in runtime
        assert f"{method}()" in audio
        assert f"{{ value: '{effect}', label: '{label}' }}" in modal


def test_workspace_pause_gates_ambient_audio():
    app = (ROOT / "static" / "app.js").read_text()
    audio = (ROOT / "static" / "audio.js").read_text()

    assert "const automationPaused = ws.config?.worker_automation_paused === true;" in app
    assert "window.ambientAudio.muteAmbient();" in app
    assert "window.ambientAudio.unmuteAmbient();" in app
    assert "muteAmbient()" in audio
    assert "unmuteAmbient()" in audio
    assert "const targetVol = this._ambientMuted ? 0 : this._ambientVolume(intensity);" in audio
    assert "if (this._ambientMuted) {" in audio
    assert "this._ambientGainTarget = 0;" in audio
    assert "_setWorkspaceAutomationPaused" not in app
    assert "_setKnownWorkspacesAutomationPaused" not in app


def test_ambient_mute_survives_until_ambient_starts():
    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "audio.js"))}, 'utf8');

class Param {{
  constructor() {{ this.value = 0; }}
  cancelScheduledValues() {{}}
  setValueAtTime(value) {{ this.value = value; }}
  linearRampToValueAtTime(value) {{ this.value = value; }}
}}
class FakeNode {{
  constructor() {{
    this.gain = new Param();
    this.frequency = new Param();
    this.Q = new Param();
    this.context = {{}};
  }}
  connect(dest) {{ this.dest = dest; return dest; }}
  start() {{}}
  stop() {{}}
  disconnect() {{}}
}}
class FakeBuffer {{
  getChannelData() {{ return new Float32Array(4); }}
}}
class FakeAudioContext {{
  constructor() {{
    this.currentTime = 0;
    this.sampleRate = 1;
    this.state = 'running';
    this.destination = {{}};
  }}
  createGain() {{ return new FakeNode(); }}
  createOscillator() {{ return new FakeNode(); }}
  createBuffer() {{ return new FakeBuffer(); }}
  createBufferSource() {{ return new FakeNode(); }}
  createBiquadFilter() {{ return new FakeNode(); }}
  resume() {{}}
}}

const context = {{
  window: {{ AudioContext: FakeAudioContext }},
  console,
  Math,
  setTimeout,
}};
vm.createContext(context);
vm.runInContext(source, context);

const audio = context.window.ambientAudio;
audio.muteAmbient();
const mutedBeforeStart = audio._ambientMuted;
audio.startAmbient('server_room', 10);
const startedMuted = audio._ambientGain.gain.value;
audio.updateAmbientIntensity(20);
const stayedMuted = audio._ambientGain.gain.value;
audio.unmuteAmbient();
const restored = audio._ambientGain.gain.value;

process.stdout.write(JSON.stringify({{ mutedBeforeStart, startedMuted, stayedMuted, restored }}));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mutedBeforeStart"] is True
    assert payload["startedMuted"] == 0
    assert payload["stayedMuted"] == 0
    assert payload["restored"] > 0


def test_ambient_duck_restores_to_original_target_after_overlapping_events():
    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "audio.js"))}, 'utf8');

class Param {{
  constructor() {{ this.value = 0; }}
  cancelScheduledValues() {{}}
  setValueAtTime(value) {{ this.value = value; }}
  linearRampToValueAtTime(value) {{ this.value = value; }}
}}
class FakeNode {{
  constructor() {{
    this.gain = new Param();
    this.frequency = new Param();
    this.Q = new Param();
    this.context = {{}};
  }}
  connect(dest) {{ this.dest = dest; return dest; }}
  start() {{}}
  stop() {{}}
  disconnect() {{}}
}}
class FakeBuffer {{
  getChannelData() {{ return new Float32Array(4); }}
}}
class FakeAudioContext {{
  constructor() {{
    this.currentTime = 0;
    this.sampleRate = 1;
    this.state = 'running';
    this.destination = {{}};
  }}
  createGain() {{ return new FakeNode(); }}
  createOscillator() {{ return new FakeNode(); }}
  createBuffer() {{ return new FakeBuffer(); }}
  createBufferSource() {{ return new FakeNode(); }}
  createBiquadFilter() {{ return new FakeNode(); }}
  resume() {{}}
}}

const context = {{
  window: {{ AudioContext: FakeAudioContext }},
  console,
  Math,
  setTimeout,
}};
vm.createContext(context);
vm.runInContext(source, context);

const audio = context.window.ambientAudio;
audio.startAmbient('server_room', 10);
const target = audio._ambientGainTarget;
audio._ambientGain.gain.value = target;
audio._duckAmbient(6, 300);

// Simulate the next event arriving while the previous duck is still attenuated.
audio._ambientGain.gain.value = target * Math.pow(10, -6 / 20);
audio._duckAmbient(6, 300);
const restoredAfterOverlap = audio._ambientGain.gain.value;

process.stdout.write(JSON.stringify({{ target, restoredAfterOverlap }}));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["target"] > 0
    assert abs(payload["restoredAfterOverlap"] - payload["target"]) < 0.000001


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
