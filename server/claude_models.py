"""Claude model catalog helpers backed by the public models.dev catalog."""

from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import certifi


MODELS_DEV_URL = "https://models.dev/api.json"
DEFAULT_CACHE_TTL_SECONDS = 60 * 60
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_IN_FLIGHT_WAIT_SECONDS = 5
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# Last-resort choices for offline startup. models.dev remains the normal source
# of truth; this list only keeps existing workers configurable when it cannot be
# reached and no last-good response exists in this process.
FALLBACK_CLAUDE_MODELS = [
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_REFRESH_CONDITION = threading.Condition(_CACHE_LOCK)
_REFRESH_IN_FLIGHT = False
_REFRESH_GENERATION = 0
_LAST_REFRESH_ERROR = None


@dataclass(frozen=True)
class ModelRecord:
    id: str
    display_name: str
    status: str = "active"
    release_date: str = ""
    last_updated: str = ""
    family: str = ""
    context_limit: int | None = None
    output_limit: int | None = None
    reasoning: bool = False
    tool_call: bool = False
    attachment: bool = False

    def as_dict(self):
        return {
            "id": self.id,
            "display_name": self.display_name,
            "status": self.status,
            "release_date": self.release_date,
            "last_updated": self.last_updated,
            "family": self.family,
            "context_limit": self.context_limit,
            "output_limit": self.output_limit,
            "reasoning": self.reasoning,
            "tool_call": self.tool_call,
            "attachment": self.attachment,
        }


def clear_claude_model_cache():
    """Clear cached catalog results, primarily for tests."""
    global _LAST_REFRESH_ERROR

    with _REFRESH_CONDITION:
        _CACHE.clear()
        _LAST_REFRESH_ERROR = None


def fallback_model_records():
    return [ModelRecord(id=model, display_name=model) for model in FALLBACK_CLAUDE_MODELS]


def _positive_int(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def parse_models_dev_catalog(data):
    """Parse active Claude records from models.dev's Anthropic provider data."""
    if not isinstance(data, dict):
        raise ValueError("models.dev catalog was not an object")
    anthropic = data.get("anthropic")
    models = anthropic.get("models") if isinstance(anthropic, dict) else None
    if not isinstance(models, dict):
        raise ValueError("models.dev catalog did not contain anthropic.models")

    records = []
    seen = set()
    for raw_id, model in models.items():
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id") or raw_id or "").strip()
        if not model_id or model_id in seen:
            continue
        status = str(model.get("status") or "active").strip().lower()
        if status == "deprecated":
            continue
        limits = model.get("limit") if isinstance(model.get("limit"), dict) else {}
        seen.add(model_id)
        records.append(ModelRecord(
            id=model_id,
            display_name=str(model.get("name") or model_id).strip(),
            status=status,
            release_date=str(model.get("release_date") or "").strip(),
            last_updated=str(model.get("last_updated") or "").strip(),
            family=str(model.get("family") or "").strip(),
            context_limit=_positive_int(limits.get("context")),
            output_limit=_positive_int(limits.get("output")),
            reasoning=model.get("reasoning") is True,
            tool_call=model.get("tool_call") is True,
            attachment=model.get("attachment") is True,
        ))

    # Newest releases lead without encoding provider-specific version rules.
    records.sort(key=lambda record: record.id)
    records.sort(key=lambda record: record.release_date, reverse=True)
    if not records:
        raise ValueError("models.dev catalog did not contain active Anthropic models")
    return records


def _download_catalog(timeout_seconds):
    request = urllib.request.Request(
        MODELS_DEV_URL,
        headers={"Accept": "application/json", "User-Agent": "Bullpen-Claude-Catalog/1"},
    )
    tls_context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(request, timeout=timeout_seconds, context=tls_context) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("models.dev catalog exceeded the response size limit")
    return parse_models_dev_catalog(json.loads(body.decode("utf-8")))


def _error_message(error):
    return str(error or "Unknown error").strip()[-1000:]


def _result(records, *, cached, source, cached_at=None, status="ok", error=None):
    result = {
        "status": status,
        "models": [record.as_dict() for record in records],
        "cached": cached,
        "source": source,
    }
    if cached_at is not None:
        result["cached_at"] = cached_at
    if error:
        result["error"] = error
    return result


def _unavailable_result(cached, message):
    if cached:
        return _result(
            cached["records"],
            cached=True,
            source="stale-cache",
            cached_at=cached["cached_at"],
            status="stale",
            error=message,
        )
    return _result(
        fallback_model_records(),
        cached=False,
        source="fallback",
        status="error",
        error=message + "; using fallback models",
    )


def _cached_result(cached):
    return _result(
        cached["records"],
        cached=True,
        source="models.dev",
        cached_at=cached["cached_at"],
    )


def _perform_refresh(timeout_seconds):
    """Download and atomically publish the active single-flight refresh."""
    global _REFRESH_IN_FLIGHT, _LAST_REFRESH_ERROR

    expected_errors = (
        OSError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    )
    try:
        records = _download_catalog(timeout_seconds)
    except Exception as error:
        message = "models.dev Claude catalog unavailable: " + _error_message(error)
        with _REFRESH_CONDITION:
            cached = _CACHE.get("models.dev")
            _LAST_REFRESH_ERROR = message
            _REFRESH_IN_FLIGHT = False
            _REFRESH_CONDITION.notify_all()
        if not isinstance(error, expected_errors):
            raise
        return _unavailable_result(cached, message)

    cached_at = time.time()
    with _REFRESH_CONDITION:
        _CACHE["models.dev"] = {"records": records, "cached_at": cached_at}
        _LAST_REFRESH_ERROR = None
        _REFRESH_IN_FLIGHT = False
        _REFRESH_CONDITION.notify_all()
    return _result(records, cached=False, source="models.dev", cached_at=cached_at)


def _start_refresh_thread(timeout_seconds, *, on_complete=None):
    """Start a previously claimed refresh and release ownership on failure."""
    global _REFRESH_IN_FLIGHT

    def run():
        result = _perform_refresh(timeout_seconds)
        if on_complete:
            on_complete(result)

    thread = threading.Thread(
        target=run,
        name="claude-model-catalog-refresh",
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        with _REFRESH_CONDITION:
            _REFRESH_IN_FLIGHT = False
            _REFRESH_CONDITION.notify_all()
        raise
    return thread


def start_claude_models_refresh(*, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, on_complete=None):
    """Claim and launch a background refresh, returning its thread or None."""
    global _REFRESH_GENERATION, _REFRESH_IN_FLIGHT, _LAST_REFRESH_ERROR

    with _REFRESH_CONDITION:
        if _REFRESH_IN_FLIGHT:
            return None
        _REFRESH_IN_FLIGHT = True
        _REFRESH_GENERATION += 1
        _LAST_REFRESH_ERROR = None
    return _start_refresh_thread(timeout_seconds, on_complete=on_complete)


def fetch_claude_models(
    *,
    refresh=False,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    cache_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
    in_flight_wait_seconds=DEFAULT_IN_FLIGHT_WAIT_SECONDS,
):
    """Return the models.dev Anthropic catalog with single-flight refreshing.

    Cache state is protected only while it is inspected or published. Network,
    TLS, response parsing, and bounded waits always happen without holding the
    cache lock.
    """
    global _REFRESH_GENERATION, _REFRESH_IN_FLIGHT, _LAST_REFRESH_ERROR

    now = time.time()
    background_refresh = False
    with _REFRESH_CONDITION:
        cached = _CACHE.get("models.dev")
        if not refresh and cached and now - cached["cached_at"] <= cache_ttl_seconds:
            return _cached_result(cached)

        if _REFRESH_IN_FLIGHT:
            # Cached callers never queue behind the upstream service. A stale
            # result remains useful while the active owner refreshes it. An
            # explicit refresh joins the owner so it can report that outcome.
            if cached and not refresh:
                return _unavailable_result(
                    cached,
                    "models.dev Claude catalog refresh is already in progress",
                )
            joined_generation = _REFRESH_GENERATION
        else:
            _REFRESH_IN_FLIGHT = True
            _REFRESH_GENERATION += 1
            _LAST_REFRESH_ERROR = None
            joined_generation = None
            background_refresh = cached is not None and not refresh

    if background_refresh:
        _start_refresh_thread(timeout_seconds)
        return _unavailable_result(
            cached,
            "models.dev Claude catalog refresh has started",
        )

    if joined_generation is not None:
        wait_seconds = max(0.0, float(in_flight_wait_seconds))
        with _REFRESH_CONDITION:
            completed = _REFRESH_CONDITION.wait_for(
                lambda: (
                    not _REFRESH_IN_FLIGHT
                    or _REFRESH_GENERATION != joined_generation
                ),
                timeout=wait_seconds,
            )
            cached = _CACHE.get("models.dev")
            if completed and cached and _LAST_REFRESH_ERROR is None:
                return _cached_result(cached)
            if completed and _LAST_REFRESH_ERROR:
                return _unavailable_result(cached, _LAST_REFRESH_ERROR)
            return _unavailable_result(
                cached,
                "models.dev Claude catalog refresh is still in progress",
            )

    return _perform_refresh(timeout_seconds)
