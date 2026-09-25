from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shell_worker_environment_supports_server_inheritance():
    modal = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text()

    assert '<option value="server_env">Inherit from Bullpen</option>' in modal
    assert "if (this.isShell && e.source === 'server_env')" in modal
    assert "return { key, source: 'server_env' };" in modal
    assert "Value is read when the worker runs." in modal
