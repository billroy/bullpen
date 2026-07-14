"""Claude model discovery backed by OpenRouter's public model catalog."""

from __future__ import annotations

import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

import certifi


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_KEY = "openrouter"
DEFAULT_CACHE_TTL_SECONDS = 60 * 60
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_IN_FLIGHT_WAIT_SECONDS = 5
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# Last-resort choices for offline startup. OpenRouter remains the normal
# discovery source; this list only keeps existing workers configurable when it
# cannot be reached and no last-good response exists in this process.
FALLBACK_CLAUDE_MODELS = [
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-opus-4-5",
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
]

# OpenRouter also retains older or routing-specific entries that are not exact
# Claude Code selections. Keep exclusions focused on demonstrated
# incompatibilities; new releases should flow through without additions here.
INCOMPATIBLE_CLAUDE_MODELS = {
    "claude-opus-4",
    "claude-sonnet-4",
    "claude-3-haiku",
    # Accepted by Claude Code 2.1.205, but silently routed to claude-opus-4-8.
    "claude-opus-4-1",
}
_VERSION_DOT = re.compile(r"(?<=\d)\.(?=\d)")

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_REFRESH_CONDITION = threading.Condition(_CACHE_LOCK)
_REFRESH_IN_FLIGHT = False
_REFRESH_GENERATION = 0
_LAST_REFRESH_ERROR = None
_TLS_CONTEXT = None
_TLS_CONTEXT_LOCK = threading.Lock()


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
    source_id: str = ""

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
            "source_id": self.source_id,
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


def _string_set(value):
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {item for item in value if isinstance(item, str)}


def openrouter_id_to_claude_slug(source_id):
    """Translate one ordinary OpenRouter Anthropic ID to a Claude CLI slug."""
    source_id = str(source_id or "").strip()
    if not source_id.startswith("anthropic/claude-"):
        return None
    slug = source_id.removeprefix("anthropic/")
    if ":" in slug or slug.endswith("-fast"):
        return None
    slug = _VERSION_DOT.sub("-", slug)
    if slug in INCOMPATIBLE_CLAUDE_MODELS:
        return None
    return slug


def _utc_date(timestamp):
    try:
        timestamp = int(timestamp)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def parse_openrouter_catalog(data):
    """Parse and translate OpenRouter's public Anthropic model entries."""
    if not isinstance(data, dict):
        raise ValueError("OpenRouter catalog was not an object")
    models = data.get("data")
    if not isinstance(models, list):
        raise ValueError("OpenRouter catalog did not contain a data array")

    records = []
    seen = set()
    for model in models:
        if not isinstance(model, dict):
            continue
        source_id = str(model.get("id") or "").strip()
        model_id = openrouter_id_to_claude_slug(source_id)
        if not model_id or model_id in seen:
            continue
        top_provider = model.get("top_provider") if isinstance(model.get("top_provider"), dict) else {}
        architecture = model.get("architecture") if isinstance(model.get("architecture"), dict) else {}
        supported = _string_set(model.get("supported_parameters"))
        input_modalities = _string_set(architecture.get("input_modalities"))
        display_name = str(model.get("name") or model_id).strip()
        if display_name.startswith("Anthropic:"):
            display_name = display_name.removeprefix("Anthropic:").strip()
        seen.add(model_id)
        records.append(ModelRecord(
            id=model_id,
            display_name=display_name,
            status="active",
            release_date=_utc_date(model.get("created")),
            family="claude",
            context_limit=_positive_int(model.get("context_length")),
            output_limit=_positive_int(top_provider.get("max_completion_tokens")),
            reasoning=bool({"reasoning", "reasoning_effort", "include_reasoning"} & supported),
            tool_call=bool({"tools", "tool_choice"} & supported),
            attachment=bool({"image", "file"} & input_modalities),
            source_id=source_id,
        ))

    # Newest releases lead; IDs provide stable ordering for equal timestamps.
    records.sort(key=lambda record: record.id)
    records.sort(key=lambda record: record.release_date, reverse=True)
    if not records:
        raise ValueError("OpenRouter catalog did not contain compatible Anthropic models")
    return records


def _get_tls_context():
    """Return the immutable CA-backed SSL context shared by this process."""
    global _TLS_CONTEXT

    if _TLS_CONTEXT is None:
        with _TLS_CONTEXT_LOCK:
            if _TLS_CONTEXT is None:
                _TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())
    return _TLS_CONTEXT


def _download_catalog(timeout_seconds):
    request = urllib.request.Request(
        OPENROUTER_MODELS_URL,
        headers={"Accept": "application/json", "User-Agent": "Bullpen-Claude-Catalog/1"},
    )
    with urllib.request.urlopen(
        request,
        timeout=timeout_seconds,
        context=_get_tls_context(),
    ) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("OpenRouter catalog exceeded the response size limit")
    return parse_openrouter_catalog(json.loads(body.decode("utf-8")))


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
        source="openrouter",
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
        message = "OpenRouter Claude catalog unavailable: " + _error_message(error)
        with _REFRESH_CONDITION:
            cached = _CACHE.get(CACHE_KEY)
            _LAST_REFRESH_ERROR = message
            _REFRESH_IN_FLIGHT = False
            _REFRESH_CONDITION.notify_all()
        if not isinstance(error, expected_errors):
            raise
        return _unavailable_result(cached, message)

    cached_at = time.time()
    with _REFRESH_CONDITION:
        _CACHE[CACHE_KEY] = {"records": records, "cached_at": cached_at}
        _LAST_REFRESH_ERROR = None
        _REFRESH_IN_FLIGHT = False
        _REFRESH_CONDITION.notify_all()
    return _result(records, cached=False, source="openrouter", cached_at=cached_at)


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
    """Return OpenRouter-derived Claude models with single-flight refreshing.

    Cache state is protected only while it is inspected or published. Network,
    TLS, response parsing, and bounded waits always happen without holding the
    cache lock.
    """
    global _REFRESH_GENERATION, _REFRESH_IN_FLIGHT, _LAST_REFRESH_ERROR

    now = time.time()
    background_refresh = False
    with _REFRESH_CONDITION:
        cached = _CACHE.get(CACHE_KEY)
        if not refresh and cached and now - cached["cached_at"] <= cache_ttl_seconds:
            return _cached_result(cached)

        if _REFRESH_IN_FLIGHT:
            # Cached callers never queue behind the upstream service. A stale
            # result remains useful while the active owner refreshes it. An
            # explicit refresh joins the owner so it can report that outcome.
            if cached and not refresh:
                return _unavailable_result(
                    cached,
                    "OpenRouter Claude catalog refresh is already in progress",
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
            "OpenRouter Claude catalog refresh has started",
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
            cached = _CACHE.get(CACHE_KEY)
            if completed and cached and _LAST_REFRESH_ERROR is None:
                return _cached_result(cached)
            if completed and _LAST_REFRESH_ERROR:
                return _unavailable_result(cached, _LAST_REFRESH_ERROR)
            return _unavailable_result(
                cached,
                "OpenRouter Claude catalog refresh is still in progress",
            )

    return _perform_refresh(timeout_seconds)
