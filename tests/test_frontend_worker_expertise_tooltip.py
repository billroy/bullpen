"""Regression checks for worker-card expertise prompt tooltip behavior."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_worker_card_header_uses_expertise_prompt_tooltip():
    text = _read("static/components/WorkerCard.js")
    assert ':title="expertiseTooltip || null"' in text
    assert "expertiseTooltip()" in text
    assert "this.worker.expertise_prompt" in text
    assert ':title="worker.name"' not in text
