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
    with _CACHE_LOCK:
        _CACHE.clear()


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


def fetch_claude_models(
    *,
    refresh=False,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    cache_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
):
    """Return the public models.dev Anthropic catalog with resilient caching."""
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get("models.dev")
        if not refresh and cached and now - cached["cached_at"] <= cache_ttl_seconds:
            return _result(
                cached["records"],
                cached=True,
                source="models.dev",
                cached_at=cached["cached_at"],
            )

        try:
            records = _download_catalog(timeout_seconds)
        except (
            OSError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ) as error:
            message = "models.dev Claude catalog unavailable: " + _error_message(error)
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

        cached_at = time.time()
        _CACHE["models.dev"] = {"records": records, "cached_at": cached_at}
        return _result(records, cached=False, source="models.dev", cached_at=cached_at)


def refresh_claude_models_at_startup():
    """Force a best-effort refresh for each newly started Bullpen server."""
    return fetch_claude_models(refresh=True)
