"""Frontend regression checks for Notification workers."""

from pathlib import Path


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
    assert "Notification workers" in toolbar
    assert "onToggleNotificationFlag" in toolbar


def test_notification_worker_card_summarizes_enabled_modes():
    utils = _read("static/utils.js")
    card = _read("static/components/WorkerCard.js")
    style = _read("static/style.css")

    assert "function notificationSummaryItems(worker)" in utils
    assert 'items.push(`speech 1) say "${text || \'notification text\'}"`);' in utils
    assert "items.push(`sound 2) sound effect: ${effect}`);" in utils
    assert "items.push(`flash 3) flash ${color} ${count} ${count === 1 ? 'time' : 'times'}`);" in utils
    assert 'items.push(`toast 4) toast "${text || \'notification text\'}"`);' in utils
    assert "window.notificationSummaryItems = notificationSummaryItems;" in utils

    assert 'v-else-if="isNotification" class="worker-card-notification"' in card
    assert 'v-for="item in notificationSummaryItems"' in card
    assert "No notification modes enabled" in card
    assert "notificationSummaryItems()" in card

    assert ".worker-card-notification {" in style
    assert ".worker-card-notification-list {" in style
