"""Regression checks for worker model options shown in the UI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_model_options_include_current_gpt5_family():
    text = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "'gpt-5.4'" in text
    assert "'gpt-5.4-mini'" in text
    assert "'gpt-5.3-codex'" in text
    assert "'gpt-5.2'" in text


def test_claude_model_options_do_not_include_removed_haiku_slug():
    text = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "'claude-haiku-4-6'" not in text
    assert "'claude-haiku-4-5-20250414'" not in text
    assert "'claude-haiku-4-5-20251001'" in text


def test_gemini_model_options_present():
    text = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "gemini:" in text
    assert "'gemini-2.5-pro'" in text
    assert "'gemini-2.5-flash'" in text


def test_model_options_defined_in_shared_constant():
    """Both components must use MODEL_OPTIONS from utils.js, not inline lists."""
    utils = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "MODEL_OPTIONS" in utils

    for component in ("WorkerConfigModal.js", "LiveAgentChatTab.js"):
        text = (ROOT / "static" / "components" / component).read_text(encoding="utf-8")
        assert "MODEL_OPTIONS[" in text, f"{component} should reference MODEL_OPTIONS"
        # Should not have inline model arrays
        assert "codex-mini-latest" not in text, f"{component} has stale inline codex models"
        assert "o4-mini" not in text, f"{component} has stale inline codex models"
