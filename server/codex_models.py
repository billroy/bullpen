"""Codex model catalog helpers."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass

from server.agents.codex_adapter import _find_codex


DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 20

# Last-resort choices when neither the refreshed nor bundled CLI catalog can be
# read. The normal UI path is driven by `codex debug models`.
FALLBACK_CODEX_MODELS = [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.2",
]

_CACHE = {}


@dataclass(frozen=True)
class ModelRecord:
    id: str
    display_name: str
    description: str = ""
    default_reasoning_effort: str | None = None
    supported_reasoning_efforts: tuple[str, ...] = ()

    def as_dict(self):
        return {
            "id": self.id,
            "display_name": self.display_name,
            "description": self.description,
            "default_reasoning_effort": self.default_reasoning_effort,
            "supported_reasoning_efforts": list(self.supported_reasoning_efforts),
        }


def clear_codex_model_cache():
    """Clear cached model catalog results, primarily for tests."""
    _CACHE.clear()


def fallback_model_records():
    return [ModelRecord(id=model, display_name=model) for model in FALLBACK_CODEX_MODELS]


def parse_codex_models_output(output):
    """Parse picker-visible models from `codex debug models` JSON output."""
    data = json.loads(output or "{}")
    models = data.get("models")
    if not isinstance(models, list):
        raise ValueError("Codex model catalog did not contain a models array")

    records = []
    seen = set()
    for model in models:
        if not isinstance(model, dict) or model.get("visibility") != "list":
            continue
        model_id = str(model.get("slug") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        reasoning = model.get("supported_reasoning_levels")
        efforts = tuple(
            str(option.get("effort")).strip()
            for option in (reasoning if isinstance(reasoning, list) else [])
            if isinstance(option, dict) and str(option.get("effort") or "").strip()
        )
        default_effort = str(model.get("default_reasoning_level") or "").strip() or None
        records.append(ModelRecord(
            id=model_id,
            display_name=str(model.get("display_name") or model_id).strip(),
            description=str(model.get("description") or "").strip(),
            default_reasoning_effort=default_effort,
            supported_reasoning_efforts=efforts,
        ))
    if not records:
        raise ValueError("Codex model catalog did not contain picker-visible models")
    return records


def _run_catalog(codex_bin, workspace, timeout_seconds, *, bundled=False):
    argv = [codex_bin, "debug", "models"]
    if bundled:
        argv.append("--bundled")
    completed = subprocess.run(
        argv,
        cwd=workspace or None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or f"Exit code {completed.returncode}").strip()
        raise RuntimeError(error)
    return parse_codex_models_output(completed.stdout)


def _error_message(error):
    message = str(error or "Unknown error").strip()
    return message[-1000:]


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


def fetch_codex_models(
    workspace,
    *,
    refresh=False,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    cache_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
):
    """Return the installed Codex CLI's picker-visible model catalog."""
    codex_bin = _find_codex()
    if not codex_bin:
        return _result(
            fallback_model_records(),
            cached=False,
            source="fallback",
            status="unavailable",
            error="Codex CLI is not available; using fallback models",
        )

    cache_key = (str(workspace or ""), codex_bin)
    now = time.time()
    if not refresh:
        cached = _CACHE.get(cache_key)
        if cached and now - cached["cached_at"] <= cache_ttl_seconds:
            return _result(
                cached["records"],
                cached=True,
                source=cached["source"],
                cached_at=cached["cached_at"],
            )

    errors = []
    for bundled, source in ((False, "refreshed"), (True, "bundled")):
        try:
            records = _run_catalog(codex_bin, workspace, timeout_seconds, bundled=bundled)
        except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError, json.JSONDecodeError) as error:
            errors.append(f"{source}: {_error_message(error)}")
            continue
        _CACHE[cache_key] = {"records": records, "cached_at": now, "source": source}
        return _result(records, cached=False, source=source, cached_at=now)

    return _result(
        fallback_model_records(),
        cached=False,
        source="fallback",
        status="error",
        error="Codex model catalog unavailable; using fallback models (" + "; ".join(errors) + ")",
    )
