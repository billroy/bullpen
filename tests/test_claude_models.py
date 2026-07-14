"""Tests for OpenRouter-backed Claude model discovery and socket events."""

import json
import threading

import bullpen
from server import claude_models
from server.app import create_app, socketio


def openrouter_catalog(models):
    return {"data": models}


def model(model_id, name, *, created=1771342990, **overrides):
    value = {
        "id": model_id,
        "name": name,
        "created": created,
        "context_length": 200000,
        "top_provider": {"max_completion_tokens": 64000},
        "supported_parameters": ["reasoning", "tools"],
        "architecture": {"input_modalities": ["text", "image", "file"]},
    }
    value.update(overrides)
    return value


def test_parse_openrouter_catalog_translates_filters_and_sorts_newest_first():
    records = claude_models.parse_openrouter_catalog(openrouter_catalog([
        model("anthropic/claude-sonnet-4.6", "Anthropic: Claude Sonnet 4.6", created=1771342990),
        model("anthropic/claude-opus-4.8", "Anthropic: Claude Opus 4.8", created=1779913703),
        model("anthropic/claude-opus-4.8-fast", "Anthropic: Claude Opus 4.8 (Fast)"),
        model("anthropic/claude-opus-4.1", "Anthropic: Claude Opus 4.1"),
        model("openai/gpt-5.6", "OpenAI: GPT-5.6"),
        model("anthropic/claude-opus-4.8", "Duplicate Opus", created=1779913703),
        model(
            "anthropic/claude-malformed-9.1",
            "Anthropic: Claude Malformed 9.1",
            supported_parameters=[{"unexpected": True}],
            architecture={"input_modalities": "text"},
        ),
        "not-an-object",
    ]))

    assert [record.id for record in records] == [
        "claude-opus-4-8",
        "claude-malformed-9-1",
        "claude-sonnet-4-6",
    ]
    assert records[0].display_name == "Claude Opus 4.8"
    assert records[0].source_id == "anthropic/claude-opus-4.8"
    assert records[0].context_limit == 200000
    assert records[0].output_limit == 64000
    assert records[0].reasoning is True
    assert records[0].tool_call is True
    assert records[0].attachment is True


def test_parse_openrouter_catalog_rejects_missing_data_array():
    try:
        claude_models.parse_openrouter_catalog({})
    except ValueError as error:
        assert "data array" in str(error)
    else:
        raise AssertionError("missing data array should fail")


def test_openrouter_id_translation_is_narrow_and_excludes_incompatible_models():
    assert claude_models.openrouter_id_to_claude_slug(
        "anthropic/claude-sonnet-4.6"
    ) == "claude-sonnet-4-6"
    assert claude_models.openrouter_id_to_claude_slug(
        "anthropic/claude-sonnet-5"
    ) == "claude-sonnet-5"
    assert claude_models.openrouter_id_to_claude_slug("openai/gpt-5.6") is None
    assert claude_models.openrouter_id_to_claude_slug(
        "anthropic/claude-opus-4.8-fast"
    ) is None
    assert claude_models.openrouter_id_to_claude_slug(
        "anthropic/claude-sonnet-4.6:beta"
    ) is None
    assert claude_models.openrouter_id_to_claude_slug(
        "anthropic/claude-opus-4.1"
    ) is None


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


def test_fetch_claude_models_does_not_hold_cache_lock_during_download(monkeypatch):
    claude_models.clear_claude_model_cache()
    started = threading.Event()
    release = threading.Event()

    def download(_timeout):
        started.set()
        assert release.wait(2)
        return [claude_models.ModelRecord("claude-opus-4-8", "Opus 4.8")]

    monkeypatch.setattr(claude_models, "_download_catalog", download)
    thread = threading.Thread(target=claude_models.fetch_claude_models)
    thread.start()
    assert started.wait(1)

    assert claude_models._CACHE_LOCK.acquire(timeout=0.2)
    claude_models._CACHE_LOCK.release()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_concurrent_empty_cache_requests_share_one_download(monkeypatch):
    claude_models.clear_claude_model_cache()
    started = threading.Event()
    release = threading.Event()
    calls = []
    results = []

    def download(_timeout):
        calls.append(True)
        started.set()
        assert release.wait(2)
        return [claude_models.ModelRecord("claude-opus-4-8", "Opus 4.8")]

    monkeypatch.setattr(claude_models, "_download_catalog", download)
    owner = threading.Thread(target=lambda: results.append(claude_models.fetch_claude_models()))
    joiner = threading.Thread(target=lambda: results.append(
        claude_models.fetch_claude_models(in_flight_wait_seconds=2)
    ))
    owner.start()
    assert started.wait(1)
    joiner.start()
    release.set()
    owner.join(timeout=2)
    joiner.join(timeout=2)

    assert not owner.is_alive()
    assert not joiner.is_alive()
    assert len(calls) == 1
    assert len(results) == 2
    assert {result["models"][0]["id"] for result in results} == {"claude-opus-4-8"}


def test_fresh_cache_remains_readable_during_forced_refresh(monkeypatch):
    claude_models.clear_claude_model_cache()
    monkeypatch.setattr(
        claude_models,
        "_download_catalog",
        lambda _timeout: [claude_models.ModelRecord("claude-opus-4-8", "Opus 4.8")],
    )
    claude_models.fetch_claude_models()

    started = threading.Event()
    release = threading.Event()

    def refresh_download(_timeout):
        started.set()
        assert release.wait(2)
        return [claude_models.ModelRecord("claude-sonnet-5", "Sonnet 5")]

    monkeypatch.setattr(claude_models, "_download_catalog", refresh_download)
    refresher = threading.Thread(target=lambda: claude_models.fetch_claude_models(refresh=True))
    refresher.start()
    assert started.wait(1)

    result = claude_models.fetch_claude_models()
    assert result["status"] == "ok"
    assert result["models"][0]["id"] == "claude-opus-4-8"
    assert refresher.is_alive()
    release.set()
    refresher.join(timeout=2)
    assert not refresher.is_alive()


def test_stale_cache_returns_immediately_during_refresh(monkeypatch):
    claude_models.clear_claude_model_cache()
    monkeypatch.setattr(
        claude_models,
        "_download_catalog",
        lambda _timeout: [claude_models.ModelRecord("claude-opus-4-8", "Opus 4.8")],
    )
    claude_models.fetch_claude_models()

    started = threading.Event()
    release = threading.Event()

    def refresh_download(_timeout):
        started.set()
        assert release.wait(2)
        return [claude_models.ModelRecord("claude-sonnet-5", "Sonnet 5")]

    monkeypatch.setattr(claude_models, "_download_catalog", refresh_download)
    refresher = threading.Thread(target=lambda: claude_models.fetch_claude_models(refresh=True))
    refresher.start()
    assert started.wait(1)

    result = claude_models.fetch_claude_models(cache_ttl_seconds=0)
    assert result["status"] == "stale"
    assert result["source"] == "stale-cache"
    assert result["models"][0]["id"] == "claude-opus-4-8"
    assert refresher.is_alive()
    release.set()
    refresher.join(timeout=2)
    assert not refresher.is_alive()


def test_expired_cache_starts_background_refresh_and_returns_stale(monkeypatch):
    claude_models.clear_claude_model_cache()
    monkeypatch.setattr(
        claude_models,
        "_download_catalog",
        lambda _timeout: [claude_models.ModelRecord("claude-opus-4-8", "Opus 4.8")],
    )
    claude_models.fetch_claude_models()

    started = threading.Event()
    release = threading.Event()

    def refresh_download(_timeout):
        started.set()
        assert release.wait(2)
        return [claude_models.ModelRecord("claude-sonnet-5", "Sonnet 5")]

    monkeypatch.setattr(claude_models, "_download_catalog", refresh_download)
    result = claude_models.fetch_claude_models(cache_ttl_seconds=0)

    assert result["status"] == "stale"
    assert result["models"][0]["id"] == "claude-opus-4-8"
    assert "refresh has started" in result["error"]
    assert started.wait(1)
    release.set()
    with claude_models._REFRESH_CONDITION:
        assert claude_models._REFRESH_CONDITION.wait_for(
            lambda: not claude_models._REFRESH_IN_FLIGHT,
            timeout=2,
        )
    refreshed = claude_models.fetch_claude_models()
    assert refreshed["models"][0]["id"] == "claude-sonnet-5"


def test_empty_cache_wait_is_bounded_while_refresh_continues(monkeypatch):
    claude_models.clear_claude_model_cache()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def download(_timeout):
        calls.append(True)
        started.set()
        assert release.wait(2)
        return [claude_models.ModelRecord("claude-opus-4-8", "Opus 4.8")]

    monkeypatch.setattr(claude_models, "_download_catalog", download)
    owner = threading.Thread(target=claude_models.fetch_claude_models)
    owner.start()
    assert started.wait(1)

    result = claude_models.fetch_claude_models(in_flight_wait_seconds=0.01)
    assert result["status"] == "error"
    assert result["source"] == "fallback"
    assert "still in progress" in result["error"]
    assert owner.is_alive()
    assert len(calls) == 1
    release.set()
    owner.join(timeout=2)
    assert not owner.is_alive()


def test_concurrent_forced_refresh_joins_active_owner(monkeypatch):
    claude_models.clear_claude_model_cache()
    started = threading.Event()
    release = threading.Event()
    calls = []
    results = []

    def download(_timeout):
        calls.append(True)
        started.set()
        assert release.wait(2)
        return [claude_models.ModelRecord("claude-sonnet-5", "Sonnet 5")]

    monkeypatch.setattr(claude_models, "_download_catalog", download)
    join_started = threading.Event()
    original_wait_for = claude_models._REFRESH_CONDITION.wait_for

    def observed_wait_for(predicate, timeout=None):
        join_started.set()
        return original_wait_for(predicate, timeout)

    monkeypatch.setattr(claude_models._REFRESH_CONDITION, "wait_for", observed_wait_for)
    owner = threading.Thread(target=lambda: results.append(
        claude_models.fetch_claude_models(refresh=True)
    ))
    joiner = threading.Thread(target=lambda: results.append(
        claude_models.fetch_claude_models(refresh=True, in_flight_wait_seconds=2)
    ))
    owner.start()
    assert started.wait(1)
    joiner.start()
    assert join_started.wait(1)
    release.set()
    owner.join(timeout=2)
    joiner.join(timeout=2)

    assert not owner.is_alive()
    assert not joiner.is_alive()
    assert len(calls) == 1
    assert len(results) == 2
    assert {result["models"][0]["id"] for result in results} == {"claude-sonnet-5"}


def test_unexpected_download_error_releases_single_flight_state(monkeypatch):
    claude_models.clear_claude_model_cache()
    monkeypatch.setattr(
        claude_models,
        "_download_catalog",
        lambda _timeout: (_ for _ in ()).throw(RuntimeError("programming defect")),
    )

    try:
        claude_models.fetch_claude_models()
    except RuntimeError as error:
        assert "programming defect" in str(error)
    else:
        raise AssertionError("unexpected errors must remain visible")

    monkeypatch.setattr(
        claude_models,
        "_download_catalog",
        lambda _timeout: [claude_models.ModelRecord("claude-sonnet-5", "Sonnet 5")],
    )
    result = claude_models.fetch_claude_models()
    assert result["status"] == "ok"
    assert result["models"][0]["id"] == "claude-sonnet-5"


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
            return json.dumps(openrouter_catalog([
                model("anthropic/claude-sonnet-5", "Anthropic: Claude Sonnet 5"),
            ])).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        seen["request"] = request
        seen["timeout"] = timeout
        seen["context"] = context
        return Response()

    monkeypatch.setattr(claude_models.urllib.request, "urlopen", fake_urlopen)
    records = claude_models._download_catalog(3)

    headers = {key.lower(): value for key, value in seen["request"].header_items()}
    assert seen["request"].full_url == "https://openrouter.ai/api/v1/models"
    assert seen["context"] is not None
    assert "authorization" not in headers
    assert "x-api-key" not in headers
    assert records[0].id == "claude-sonnet-5"


def test_download_catalog_reuses_one_tls_context_per_process(monkeypatch):
    created = []
    contexts = []
    shared_context = object()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(openrouter_catalog([
                model("anthropic/claude-sonnet-5", "Anthropic: Claude Sonnet 5"),
            ])).encode("utf-8")

    def create_context(*, cafile):
        created.append(cafile)
        return shared_context

    def fake_urlopen(_request, timeout, context):
        assert timeout == 3
        contexts.append(context)
        return Response()

    monkeypatch.setattr(claude_models, "_TLS_CONTEXT", None)
    monkeypatch.setattr(claude_models.ssl, "create_default_context", create_context)
    monkeypatch.setattr(claude_models.urllib.request, "urlopen", fake_urlopen)

    claude_models._download_catalog(3)
    claude_models._download_catalog(3)

    assert created == [claude_models.certifi.where()]
    assert contexts == [shared_context, shared_context]


def test_server_start_launches_background_catalog_refresh(monkeypatch):
    calls = []

    def start_refresh(**kwargs):
        calls.append(kwargs)
        thread = threading.Thread(target=lambda: kwargs["on_complete"]({"status": "ok"}))
        thread.start()
        return thread

    monkeypatch.setattr(claude_models, "start_claude_models_refresh", start_refresh)

    thread = bullpen.start_claude_catalog_refresh()
    thread.join(timeout=2)

    assert len(calls) == 1
    assert callable(calls[0]["on_complete"])
    assert not thread.is_alive()


def test_startup_refresh_claims_single_flight_before_returning(monkeypatch):
    claude_models.clear_claude_model_cache()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def download(_timeout):
        calls.append(True)
        started.set()
        assert release.wait(2)
        return [claude_models.ModelRecord("claude-opus-4-8", "Opus 4.8")]

    monkeypatch.setattr(claude_models, "_download_catalog", download)
    thread = claude_models.start_claude_models_refresh()

    assert thread is not None
    with claude_models._REFRESH_CONDITION:
        assert claude_models._REFRESH_IN_FLIGHT is True
    assert started.wait(1)
    joined = claude_models.fetch_claude_models(in_flight_wait_seconds=0.01)
    assert joined["source"] == "fallback"
    assert len(calls) == 1
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_claude_models_event_returns_catalog(monkeypatch, tmp_workspace):
    monkeypatch.setattr(claude_models, "fetch_claude_models", lambda **kwargs: {
        "status": "ok",
        "models": [{"id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"}],
        "cached": False,
        "source": "openrouter",
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
    assert data["source"] == "openrouter"
    assert data["models"][0]["id"] == "claude-sonnet-5"
    client.disconnect()
