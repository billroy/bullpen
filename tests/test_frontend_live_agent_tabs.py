"""Regression checks for multiple Live Agent tabs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_live_agent_tabs_are_dynamic_in_app_shell():
    text = _read("static/app.js")
    assert "const chatTabs = reactive([]);" in text
    assert "function addLiveAgentTab({ activate = true } = {})" in text
    assert "function closeLiveAgentTab(tabId)" in text
    assert "class=\"tab-btn tab-btn-add\"" in text
    assert "v-for=\"ct in chatTabs\"" in text
    assert ":session-id=\"ct.sessionId\"" in text


def test_live_agent_seed_does_not_override_default_tickets_tab():
    text = _read("static/app.js")
    assert "const activeTab = ref('tasks');" in text
    assert "addLiveAgentTab({ activate: false });" in text


def test_live_agent_component_uses_injected_session_id():
    text = _read("static/components/LiveAgentChatTab.js")
    assert "props:" in text
    assert "sessionId" in text
    assert "activeSessionId: this.sessionId || _generateChatSessionId()" in text
    assert "data.sessionId !== this.activeSessionId" in text
    assert "sessionId: this.activeSessionId" in text
