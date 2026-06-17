"""Tests for OpenCode model catalog helpers and socket events."""

from pathlib import Path
import subprocess

from server.app import create_app, socketio
from server import opencode_models


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "opencode"


class Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_parse_opencode_models_output():
    output = (FIXTURES_DIR / "models_opencode.txt").read_text(encoding="utf-8")

    records = opencode_models.parse_opencode_models_output(output)

    assert [record.id for record in records] == [
        "opencode/big-pickle",
        "opencode/deepseek-v4-flash-free",
        "opencode/mimo-v2.5-free",
        "opencode/nemotron-3-ultra-free",
        "opencode/north-mini-code-free",
    ]
    assert records[0].provider == "opencode"
    assert records[0].model == "big-pickle"


def test_fetch_opencode_models_uses_cache(monkeypatch, tmp_path):
    opencode_models.clear_opencode_model_cache()
    output = "opencode/north-mini-code-free\n"
    calls = []

    monkeypatch.setattr(opencode_models, "_find_opencode", lambda: "/usr/local/bin/opencode")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Completed(stdout=output)

    monkeypatch.setattr(opencode_models.subprocess, "run", fake_run)

    first = opencode_models.fetch_opencode_models(str(tmp_path), provider="opencode")
    second = opencode_models.fetch_opencode_models(str(tmp_path), provider="opencode")

    assert first["status"] == "ok"
    assert first["cached"] is False
    assert second["status"] == "ok"
    assert second["cached"] is True
    assert len(calls) == 1


def test_fetch_opencode_models_refresh_bypasses_cache(monkeypatch, tmp_path):
    opencode_models.clear_opencode_model_cache()
    calls = []

    monkeypatch.setattr(opencode_models, "_find_opencode", lambda: "/usr/local/bin/opencode")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Completed(stdout="opencode/north-mini-code-free\n")

    monkeypatch.setattr(opencode_models.subprocess, "run", fake_run)

    opencode_models.fetch_opencode_models(str(tmp_path), provider="opencode")
    refreshed = opencode_models.fetch_opencode_models(str(tmp_path), provider="opencode", refresh=True)

    assert refreshed["status"] == "ok"
    assert calls[-1] == ["/usr/local/bin/opencode", "models", "--refresh", "opencode"]
    assert len(calls) == 2


def test_fetch_opencode_models_reports_missing_binary(monkeypatch, tmp_path):
    opencode_models.clear_opencode_model_cache()
    monkeypatch.setattr(opencode_models, "_find_opencode", lambda: None)

    result = opencode_models.fetch_opencode_models(str(tmp_path))

    assert result["status"] == "unavailable"
    assert result["models"] == []
    assert "not available" in result["error"]


def test_fetch_opencode_models_reports_subprocess_error(monkeypatch, tmp_path):
    opencode_models.clear_opencode_model_cache()
    monkeypatch.setattr(opencode_models, "_find_opencode", lambda: "/usr/local/bin/opencode")
    monkeypatch.setattr(
        opencode_models.subprocess,
        "run",
        lambda *args, **kwargs: Completed(stderr="auth failed", returncode=1),
    )

    result = opencode_models.fetch_opencode_models(str(tmp_path))

    assert result["status"] == "error"
    assert result["models"] == []
    assert result["error"] == "auth failed"


def test_fetch_opencode_models_reports_timeout(monkeypatch, tmp_path):
    opencode_models.clear_opencode_model_cache()
    monkeypatch.setattr(opencode_models, "_find_opencode", lambda: "/usr/local/bin/opencode")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=20)

    monkeypatch.setattr(opencode_models.subprocess, "run", fake_run)

    result = opencode_models.fetch_opencode_models(str(tmp_path))

    assert result["status"] == "error"
    assert "timed out" in result["error"]


def test_opencode_models_event_returns_catalog(monkeypatch, tmp_workspace):
    def fake_fetch(workspace, **kwargs):
        return {
            "status": "ok",
            "models": [{"id": "opencode/north-mini-code-free", "provider": "opencode", "model": "north-mini-code-free"}],
            "cached": False,
            "provider": kwargs.get("provider") or None,
        }

    monkeypatch.setattr(opencode_models, "fetch_opencode_models", fake_fetch)
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("models:opencode", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "models-one",
        "provider": "opencode",
        "refresh": True,
    })

    data = next(
        event["args"][0]
        for event in client.get_received()
        if event["name"] == "models:opencode:listed"
    )
    assert data["request_id"] == "models-one"
    assert data["status"] == "ok"
    assert data["provider"] == "opencode"
    assert data["models"][0]["id"] == "opencode/north-mini-code-free"
    client.disconnect()


def test_opencode_models_rest_route_is_removed(tmp_workspace):
    app = create_app(tmp_workspace, no_browser=True)

    routes = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/models/opencode" not in routes
