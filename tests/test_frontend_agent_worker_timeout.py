"""Regression checks for per-agent worker timeout controls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_worker_timeout_uses_workspace_default_and_allows_zero():
    modal = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "workspaceAgentTimeoutSeconds" in modal
    assert "w.timeout_seconds ?? (isAiForm ? (this.workspaceAgentTimeoutSeconds ?? 1200) : 60)" in modal
    assert 'v-model.number="form.timeout_seconds" min="0" step="1"' in modal
    assert "Use 0 for no timeout" in modal
    assert ':workspace-agent-timeout-seconds="state.config.agent_timeout_seconds ?? 1200"' in app
