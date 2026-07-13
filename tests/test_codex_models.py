"""Tests for Codex model discovery and socket events."""

import json
import subprocess

from server.app import create_app, socketio
from server import codex_models


class Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def catalog(*models):
    return json.dumps({"models": list(models)})


def visible(slug, **overrides):
    model = {
        "slug": slug,
        "display_name": slug.upper(),
        "description": f"Description for {slug}",
        "visibility": "list",
        "default_reasoning_level": "medium",
        "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
    }
    model.update(overrides)
    return model


def test_parse_codex_models_output_keeps_visible_order_and_metadata():
    records = codex_models.parse_codex_models_output(catalog(
        visible("gpt-5.6-sol"),
        visible("hidden-model", visibility="hidden"),
        visible("gpt-5.6-terra"),
        visible("gpt-5.6-sol"),
    ))

    assert [record.id for record in records] == ["gpt-5.6-sol", "gpt-5.6-terra"]
    assert records[0].display_name == "GPT-5.6-SOL"
    assert records[0].default_reasoning_effort == "medium"
    assert records[0].supported_reasoning_efforts == ("low", "high")


def test_fetch_codex_models_uses_cache(monkeypatch, tmp_path):
    codex_models.clear_codex_model_cache()
    calls = []
    monkeypatch.setattr(codex_models, "_find_codex", lambda: "/usr/local/bin/codex")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Completed(stdout=catalog(visible("gpt-5.6-sol")))

    monkeypatch.setattr(codex_models.subprocess, "run", fake_run)

    first = codex_models.fetch_codex_models(str(tmp_path))
    second = codex_models.fetch_codex_models(str(tmp_path))

    assert first["source"] == "refreshed"
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(calls) == 1


def test_fetch_codex_models_refresh_bypasses_cache(monkeypatch, tmp_path):
    codex_models.clear_codex_model_cache()
    calls = []
    monkeypatch.setattr(codex_models, "_find_codex", lambda: "/usr/local/bin/codex")
    monkeypatch.setattr(
        codex_models.subprocess,
        "run",
        lambda argv, **kwargs: calls.append(argv) or Completed(stdout=catalog(visible("gpt-5.6-sol"))),
    )

    codex_models.fetch_codex_models(str(tmp_path))
    codex_models.fetch_codex_models(str(tmp_path), refresh=True)

    assert calls == [
        ["/usr/local/bin/codex", "debug", "models"],
        ["/usr/local/bin/codex", "debug", "models"],
    ]


def test_fetch_codex_models_uses_bundled_catalog_after_refresh_error(monkeypatch, tmp_path):
    codex_models.clear_codex_model_cache()
    calls = []
    monkeypatch.setattr(codex_models, "_find_codex", lambda: "/usr/local/bin/codex")

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "--bundled" not in argv:
            return Completed(stderr="network unavailable", returncode=1)
        return Completed(stdout=catalog(visible("gpt-5.5")))

    monkeypatch.setattr(codex_models.subprocess, "run", fake_run)

    result = codex_models.fetch_codex_models(str(tmp_path))

    assert result["status"] == "ok"
    assert result["source"] == "bundled"
    assert result["models"][0]["id"] == "gpt-5.5"
    assert calls[-1] == ["/usr/local/bin/codex", "debug", "models", "--bundled"]


def test_fetch_codex_models_returns_fallback_when_cli_is_missing(monkeypatch, tmp_path):
    codex_models.clear_codex_model_cache()
    monkeypatch.setattr(codex_models, "_find_codex", lambda: None)

    result = codex_models.fetch_codex_models(str(tmp_path))

    assert result["status"] == "unavailable"
    assert result["source"] == "fallback"
    assert [model["id"] for model in result["models"]] == codex_models.FALLBACK_CODEX_MODELS


def test_fetch_codex_models_returns_fallback_after_timeout(monkeypatch, tmp_path):
    codex_models.clear_codex_model_cache()
    monkeypatch.setattr(codex_models, "_find_codex", lambda: "/usr/local/bin/codex")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], timeout=20)

    monkeypatch.setattr(codex_models.subprocess, "run", fake_run)

    result = codex_models.fetch_codex_models(str(tmp_path))

    assert result["status"] == "error"
    assert result["source"] == "fallback"
    assert "timed out" in result["error"]


def test_codex_models_event_returns_catalog(monkeypatch, tmp_workspace):
    monkeypatch.setattr(codex_models, "fetch_codex_models", lambda workspace, **kwargs: {
        "status": "ok",
        "models": [{"id": "gpt-5.6-sol", "display_name": "GPT-5.6-Sol"}],
        "cached": False,
        "source": "refreshed",
    })
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("models:codex", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "codex-models-one",
        "refresh": True,
    })

    data = next(
        event["args"][0]
        for event in client.get_received()
        if event["name"] == "models:codex:listed"
    )
    assert data["request_id"] == "codex-models-one"
    assert data["status"] == "ok"
    assert data["models"][0]["id"] == "gpt-5.6-sol"
    client.disconnect()
