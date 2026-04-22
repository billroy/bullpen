"""Regression checks for Procfile-backed Service worker UI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_worker_config_modal_exposes_service_procfile_controls():
    text = _read("static/components/WorkerConfigModal.js")
    assert "Command Source" in text
    assert 'option value="manual">Manual command' in text
    assert 'option value="procfile">Procfile' in text
    assert "Procfile process" in text
    assert "Resolved command preview" in text
    assert "fetch('/api/service/preview'" in text
    assert "Suggested open port:" in text
    assert "data.suggested_port" in text
    assert "servicePortAutoFilled" in text
    assert "activation: w.activation || (w.type === 'service' ? 'manual' : 'on_drop')" in text


def test_worker_card_hides_procfile_badge_and_conditionally_appends_port_to_title():
    text = _read("static/components/WorkerCard.js")
    assert "Procfile:${this.worker.procfile_process || 'web'}" not in text
    assert "titlePortCandidate()" in text
    assert "workerNameWithPort()" in text
    assert "recalculateTitlePortVisibility()" in text


def test_add_service_worker_defaults_to_manual_activation():
    text = _read("static/components/BullpenTab.js")
    assert "name: 'Service worker'" in text
    assert "activation: 'manual'" in text
