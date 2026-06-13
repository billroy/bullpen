"""OpenCode model catalog helpers."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from server.agents.opencode_adapter import _find_opencode


DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 20

_CACHE = {}


@dataclass(frozen=True)
class ModelRecord:
    id: str
    provider: str
    model: str

    def as_dict(self):
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
        }


def clear_opencode_model_cache():
    """Clear cached model catalog results, primarily for tests."""
    _CACHE.clear()


def parse_opencode_models_output(output):
    """Parse `opencode models` plain output into model records."""
    records = []
    seen = set()
    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("{") or line.startswith("}"):
            continue
        if "/" not in line:
            continue
        provider, model = line.split("/", 1)
        provider = provider.strip()
        model = model.strip()
        if not provider or not model:
            continue
        model_id = f"{provider}/{model}"
        if model_id in seen:
            continue
        seen.add(model_id)
        records.append(ModelRecord(id=model_id, provider=provider, model=model))
    return records


def fetch_opencode_models(
    workspace,
    *,
    provider=None,
    refresh=False,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    cache_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
):
    """Return a structured OpenCode model catalog response.

    Errors are returned as data instead of raised so the frontend can keep
    custom model entry available when the catalog is unavailable.
    """
    opencode_bin = _find_opencode()
    if not opencode_bin:
        return {
            "status": "unavailable",
            "error": "OpenCode CLI is not available",
            "models": [],
            "cached": False,
        }

    provider = str(provider or "").strip()
    cache_key = (str(workspace or ""), opencode_bin, provider)
    now = time.time()
    if not refresh:
        cached = _CACHE.get(cache_key)
        if cached and now - cached["cached_at"] <= cache_ttl_seconds:
            return {
                "status": "ok",
                "models": [record.as_dict() for record in cached["records"]],
                "cached": True,
                "cached_at": cached["cached_at"],
                "provider": provider or None,
            }

    argv = [opencode_bin, "models"]
    if refresh:
        argv.append("--refresh")
    if provider:
        argv.append(provider)

    try:
        completed = subprocess.run(
            argv,
            cwd=workspace or None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return {
            "status": "unavailable",
            "error": "OpenCode CLI is not available",
            "models": [],
            "cached": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"OpenCode model catalog timed out after {timeout_seconds}s",
            "models": [],
            "cached": False,
        }

    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or f"Exit code {completed.returncode}").strip()
        return {
            "status": "error",
            "error": error,
            "models": [],
            "cached": False,
        }

    records = parse_opencode_models_output(completed.stdout)
    _CACHE[cache_key] = {"records": records, "cached_at": now}
    return {
        "status": "ok",
        "models": [record.as_dict() for record in records],
        "cached": False,
        "cached_at": now,
        "provider": provider or None,
    }
