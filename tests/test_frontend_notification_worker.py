"""Frontend regression checks for Notification workers."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_notification_worker_runtime_is_loaded_and_initialized():
    index = _read("static/index.html")
    app = _read("static/app.js")

    assert '<script src="/notification-worker.js"></script>' in index
    assert "window.NotificationWorkers.init(socket)" in app
    assert "socket.on('toast'" in app


def test_notification_worker_config_modal_fields_exist():
    text = _read("static/components/WorkerConfigModal.js")

    assert "isNotification()" in text
    assert "form.notification.toast.template" in text
    assert "form.notification.speech.template" in text
    assert "KOKORO_VOICE_OPTIONS" in text
    assert "af_heart" in text
    assert "af_bella" in text
    assert "placeholder=\"Global default\"" not in text
    assert "form.notification.sound.effect" in text
    assert "previewNotificationSound" in text
    assert "aria-label=\"Preview sound effect\"" in text
    assert "form.notification.flash.sequence" in text
    assert "form.notification.policy.cooldown_ms" in text
    assert "{ticket.title}" in text


def test_notification_worker_exposes_expanded_sound_effects():
    modal = _read("static/components/WorkerConfigModal.js")
    runtime = _read("static/notification-worker.js")
    audio = _read("static/audio.js")

    assert "const NOTIFICATION_SOUND_OPTIONS = [" in modal
    assert modal.count("value: '") >= 30
    for effect, method in {
        "bell": "playBell",
        "critical": "playCritical",
        "double_tick": "playDoubleTick",
        "ripple": "playRipple",
        "upload": "playUpload",
        "download": "playDownload",
    }.items():
        assert f"value: '{effect}'" in modal
        assert f"{effect}: '{method}'" in runtime
        assert f"{method}()" in audio


def test_notification_worker_runtime_caps_and_settings_exist():
    text = _read("static/notification-worker.js")
    toolbar = _read("static/components/TopToolbar.js")

    assert "const VISIBLE_TOASTS = 3" in text
    assert "KOKORO_IMPORT_URL" in text
    assert "loadKokoro()" in text
    assert "_speakKokoro" in text
    assert "notification:fire" in text
    assert "if (payload.ephemeral) return;" in text
    assert "prefers-reduced-motion: reduce" in text
    assert "stopSpeech()" in text
    assert "window.ambientAudio.setVolume?.(volume)" in text
    assert "_startAmbientSpeechDuck" in text
    assert "audio._holdAmbientDuck(6)" in text
    assert "this._currentSpeechDuckRelease?.();" in text
    assert "Notification workers" in toolbar
    assert "onToggleNotificationFlag" in toolbar


def test_notification_worker_card_summarizes_enabled_modes():
    utils = _read("static/utils.js")
    card = _read("static/components/WorkerCard.js")
    style = _read("static/style.css")

    assert "function notificationSummaryItems(worker)" in utils
    assert 'items.push(`Say "${text || \'notification text\'}"`);' in utils
    assert "items.push(`Play ${effect.replaceAll('_', ' ')} sound`);" in utils
    assert "items.push(`Flash ${color} ${count} ${count === 1 ? 'time' : 'times'}`);" in utils
    assert 'items.push(`Show toast "${text || \'notification text\'}"`);' in utils
    assert "speech 1)" not in utils
    assert "sound 2)" not in utils
    assert "flash 3)" not in utils
    assert "toast 4)" not in utils
    assert "window.notificationSummaryItems = notificationSummaryItems;" in utils

    assert 'v-else-if="isNotification" class="worker-card-notification"' in card
    assert 'v-for="item in notificationSummaryItems"' in card
    assert "No notification modes enabled" in card
    assert "notificationSummaryItems()" in card

    assert ".worker-card-notification {" in style
    assert ".worker-card-notification-list {" in style


def test_notification_worker_card_summary_is_human_readable():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static/utils.js"))}, 'utf8');
const context = {{
  window: {{ location: {{ href: 'http://127.0.0.1:5050/', hostname: '127.0.0.1' }} }},
  URL,
}};
vm.createContext(context);
vm.runInContext(source, context);
const items = context.window.notificationSummaryItems({{
  type: 'notification',
  notification: {{
    speech: {{ enabled: true, template: 'Build finished' }},
    sound: {{ enabled: true, effect: 'double_tick' }},
    flash: {{ enabled: true, sequence: [{{ color: '#22c55e' }}, {{ color: '#22c55e' }}] }},
    toast: {{ enabled: true, template: 'Deploy {{ticket.title}}' }},
  }},
}});
console.log(JSON.stringify(items));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        'Say "Build finished"',
        "Play double tick sound",
        "Flash #22c55e 2 times",
        'Show toast "Deploy {ticket.title}"',
    ]
