"""Regression checks for worker model options shown in the UI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_model_options_include_current_gpt5_family():
    text = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "codex: ['gpt-5.5'" in text
    assert "'gpt-5.4'" in text
    assert "'gpt-5.4-mini'" in text
    assert "'gpt-5.3-codex'" in text
    assert "'gpt-5.2'" in text


def test_claude_model_options_do_not_include_removed_haiku_slug():
    text = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "'claude-opus-4-7'" in text
    assert "'claude-haiku-4-6'" not in text
    assert "'claude-haiku-4-5-20250414'" not in text
    assert "'claude-haiku-4-5-20251001'" in text


def test_antigravity_model_options_present_and_gemini_provider_absent():
    text = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "antigravity:" in text
    assert "'Gemini 3.5 Flash (Medium)'" in text
    assert "'Claude Sonnet 4.6 (Thinking)'" in text
    assert "'GPT-OSS 120B (Medium)'" in text
    assert "gemini:" not in text
    assert "'gemini-2.5-flash'" not in text
    assert "'gemini-2.5-flash-lite'" not in text
    assert "'gemini-2.5-pro'" not in text
    assert "'gemini-3-pro-preview'" not in text
    assert "'pro'" not in text
    assert "'auto-gemini-2.5'" not in text
    assert "'gemini-2.0-flash'" not in text


def test_opencode_uses_catalog_backed_model_picker():
    utils = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    modal = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "opencode: []" in utils
    assert "agentOptions()" in modal
    assert "agentLabel(agent)" in modal
    assert "isOpenCodeAgent()" in modal
    assert "/api/models/opencode" in modal
    assert "opencodeModelProvider" in modal
    assert "filteredOpenCodeModels" in modal
    assert "refreshOpenCodeModels" in modal
    assert 'placeholder="provider/model"' in modal
    assert "BULLPEN_OPENCODE_PATH" in modal
    assert ':active-workspace-id="activeWorkspaceId"' in app
    assert ':last-ai-selection="globalSettings.last_ai_selection"' in app


def test_live_agent_chat_exposes_opencode_catalog_picker():
    text = (ROOT / "static" / "components" / "LiveAgentChatTab.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert "AI_PROVIDER_OPTIONS" in text
    assert "withPreferredOption" in text
    assert "isOpenCodeProvider()" in text
    assert "/api/models/opencode" in text
    assert "opencodeModelProvider" in text
    assert "filteredOpenCodeModels" in text
    assert "refreshOpenCodeModels" in text
    assert 'placeholder="provider/model"' in text
    assert "BULLPEN_OPENCODE_PATH" in text
    assert "chat-model-select" in css


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


def test_last_ai_selection_promotes_provider_and_model_options():
    utils = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    modal = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text(encoding="utf-8")
    chat = (ROOT / "static" / "components" / "LiveAgentChatTab.js").read_text(encoding="utf-8")

    assert "function normalizedLastAiSelection" in utils
    assert "function withPreferredOption" in utils
    assert "socket.on('global:settings'" in app
    assert "lastAiSelection" in modal
    assert "withPreferredOption(AI_PROVIDER_OPTIONS" in modal
    assert "preferred?.agent === this.form.agent ? preferred.model" in modal
    assert "lastAiSelection" in chat
    assert "withPreferredOption(AI_PROVIDER_OPTIONS" in chat
    assert "preferred?.agent === this.provider ? preferred.model" in chat
