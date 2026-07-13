"""Tests for models.dev-backed Claude model discovery and socket events."""

import json

import bullpen
from server import claude_models
from server.app import create_app, socketio


def models_dev_catalog(models):
    return {"anthropic": {"models": models}}


def model(name, *, status=None, release_date="2026-01-01", **overrides):
    value = {
        "name": name,
        "release_date": release_date,
        "last_updated": release_date,
        "family": "claude",
        "reasoning": True,
        "tool_call": True,
        "attachment": True,
        "limit": {"context": 200000, "output": 64000},
    }
    if status is not None:
        value["status"] = status
    value.update(overrides)
    return value


def test_parse_models_dev_catalog_filters_deprecated_and_sorts_newest_first():
    records = claude_models.parse_models_dev_catalog(models_dev_catalog({
        "claude-sonnet-4-6": model("Claude Sonnet 4.6", release_date="2026-02-17"),
        "claude-opus-4-8": model("Claude Opus 4.8", release_date="2026-05-28"),
        "claude-opus-4-1": model("Claude Opus 4.1", status="deprecated", release_date="2025-08-05"),
        "duplicate-opus": model("Duplicate Opus", id="claude-opus-4-8", release_date="2026-05-28"),
        "malformed": "not-an-object",
    }))

    assert [record.id for record in records] == ["claude-opus-4-8", "claude-sonnet-4-6"]
    assert records[0].display_name == "Claude Opus 4.8"
    assert records[0].context_limit == 200000
    assert records[0].reasoning is True


def test_parse_models_dev_catalog_rejects_missing_anthropic_models():
    try:
        claude_models.parse_models_dev_catalog({"anthropic": {}})
    except ValueError as error:
        assert "anthropic.models" in str(error)
    else:
        raise AssertionError("missing anthropic.models should fail")


def test_fetch_claude_models_uses_one_hour_cache(monkeypatch):
    claude_models.clear_claude_model_cache()
    calls = []
    monkeypatch.setattr(
        claude_models,
        "_download_catalog",
        lambda timeout: calls.append(timeout) or [claude_models.ModelRecord("claude-opus-4-8", "Opus 4.8")],
    )

    first = claude_models.fetch_claude_models()
    second = claude_models.fetch_claude_models()

    assert claude_models.DEFAULT_CACHE_TTL_SECONDS == 3600
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(calls) == 1


def test_fetch_claude_models_refresh_bypasses_cache(monkeypatch):
    claude_models.clear_claude_model_cache()
    calls = []
    monkeypatch.setattr(
        claude_models,
        "_download_catalog",
        lambda timeout: calls.append(timeout) or [claude_models.ModelRecord("claude-sonnet-5", "Sonnet 5")],
    )

    claude_models.fetch_claude_models()
    claude_models.fetch_claude_models(refresh=True)

    assert len(calls) == 2


def test_fetch_claude_models_preserves_last_good_catalog_on_refresh_error(monkeypatch):
    claude_models.clear_claude_model_cache()
    responses = iter([
        [claude_models.ModelRecord("claude-opus-4-8", "Opus 4.8")],
        OSError("network unavailable"),
    ])

    def download(_timeout):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(claude_models, "_download_catalog", download)
    claude_models.fetch_claude_models()
    result = claude_models.fetch_claude_models(refresh=True)

    assert result["status"] == "stale"
    assert result["source"] == "stale-cache"
    assert result["models"][0]["id"] == "claude-opus-4-8"


def test_fetch_claude_models_uses_fallback_without_last_good_catalog(monkeypatch):
    claude_models.clear_claude_model_cache()
    monkeypatch.setattr(claude_models, "_download_catalog", lambda _timeout: (_ for _ in ()).throw(OSError("offline")))

    result = claude_models.fetch_claude_models()

    assert result["status"] == "error"
    assert result["source"] == "fallback"
    assert [row["id"] for row in result["models"]] == claude_models.FALLBACK_CLAUDE_MODELS


def test_download_catalog_sends_no_credentials(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(models_dev_catalog({
                "claude-sonnet-5": model("Claude Sonnet 5"),
            })).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        seen["request"] = request
        seen["timeout"] = timeout
        seen["context"] = context
        return Response()

    monkeypatch.setattr(claude_models.urllib.request, "urlopen", fake_urlopen)
    records = claude_models._download_catalog(3)

    headers = {key.lower(): value for key, value in seen["request"].header_items()}
    assert seen["request"].full_url == "https://models.dev/api.json"
    assert seen["context"] is not None
    assert "authorization" not in headers
    assert "x-api-key" not in headers
    assert records[0].id == "claude-sonnet-5"


def test_startup_refresh_forces_catalog_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(
        claude_models,
        "fetch_claude_models",
        lambda **kwargs: calls.append(kwargs) or {"status": "ok", "models": []},
    )

    result = claude_models.refresh_claude_models_at_startup()

    assert calls == [{"refresh": True}]
    assert result["status"] == "ok"


def test_server_start_launches_background_catalog_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(
        claude_models,
        "refresh_claude_models_at_startup",
        lambda: calls.append(True) or {"status": "ok"},
    )

    thread = bullpen.start_claude_catalog_refresh()
    thread.join(timeout=2)

    assert calls == [True]
    assert not thread.is_alive()


def test_claude_models_event_returns_catalog(monkeypatch, tmp_workspace):
    monkeypatch.setattr(claude_models, "fetch_claude_models", lambda **kwargs: {
        "status": "ok",
        "models": [{"id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"}],
        "cached": False,
        "source": "models.dev",
    })
    app = create_app(tmp_workspace, no_browser=True)
    client = socketio.test_client(app)
    client.get_received()

    client.emit("models:claude", {
        "workspaceId": app.config["startup_workspace_id"],
        "request_id": "claude-models-one",
        "refresh": True,
    })

    data = next(
        event["args"][0]
        for event in client.get_received()
        if event["name"] == "models:claude:listed"
    )
    assert data["request_id"] == "claude-models-one"
    assert data["source"] == "models.dev"
    assert data["models"][0]["id"] == "claude-sonnet-5"
    client.disconnect()
