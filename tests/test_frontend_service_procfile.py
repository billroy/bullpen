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


def test_worker_card_shows_procfile_mode_and_port_badges():
    text = _read("static/components/WorkerCard.js")
    assert "serviceModeBadge()" in text
    assert "Procfile:${this.worker.procfile_process || 'web'}" in text
    assert "servicePortLabel()" in text
