"""Regression checks for worker model options shown in WorkerConfigModal."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_model_options_include_current_gpt5_family():
    text = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text(encoding="utf-8")
    assert "'gpt-5.4'" in text
    assert "'gpt-5.4-mini'" in text
    assert "'gpt-5.3-codex'" in text
    assert "'gpt-5.2'" in text
