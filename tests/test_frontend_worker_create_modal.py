"""Regression checks for worker creation opening the config modal."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_worker_library_creation_waits_for_layout_echo_before_configuring():
    text = _read("static/components/BullpenTab.js")

    assert "createWorkerAndOpenConfig({ type, profile, fields })" in text
    assert "pendingWorkerAdd: null" in text
    assert "resolvePendingWorkerAdd()" in text
    assert "this.$emit('configure-worker', item.slotIndex);" in text
    assert "this.$emit('configure-worker', slot);" not in text
    assert "if (this.pendingWorkerAdd) return;" in text
    assert "this.pendingWorkerAddTimer = setTimeout(() => {" in text
    assert "this.createWorkerAndOpenConfig({ profile: profileId, type: 'ai' });" in text
    assert "this.createWorkerAndOpenConfig({" in text
    assert "type: 'shell'," in text
    assert "type: 'service'," in text
    assert "type: 'marker'," in text
    assert "type: 'notification'," in text
    assert "addNotificationWorker()" in text
