"""Cross-project Bullpen settings stored outside individual workspaces."""

from __future__ import annotations

import os
from typing import Any

from server.model_aliases import normalize_model
from server.persistence import read_json, write_json
from server.validation import VALID_AGENTS


SETTINGS_VERSION = 1
SETTINGS_FILENAME = "settings.json"
MAX_MODEL_LEN = 128


def _settings_path(global_dir: str) -> str:
    return os.path.join(global_dir, SETTINGS_FILENAME)


def _normalize_ai_selection(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    agent = str(value.get("agent") or "").strip()
    model = str(value.get("model") or "").strip()
    if agent not in VALID_AGENTS or not model:
        return None
    model = normalize_model(agent, model[:MAX_MODEL_LEN])
    return {"agent": agent, "model": model}


def load_global_settings(global_dir: str) -> dict[str, Any]:
    """Return sanitized global settings for browser clients and server defaults."""
    try:
        raw = read_json(_settings_path(global_dir))
    except (FileNotFoundError, OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    settings: dict[str, Any] = {"version": SETTINGS_VERSION}
    selection = _normalize_ai_selection(raw.get("last_ai_selection"))
    if selection:
        settings["last_ai_selection"] = selection
    return settings


def remember_ai_selection(global_dir: str, agent: str, model: str) -> dict[str, Any]:
    """Persist the last selected AI provider/model across all projects."""
    selection = _normalize_ai_selection({"agent": agent, "model": model})
    if not selection:
        return load_global_settings(global_dir)

    settings = load_global_settings(global_dir)
    settings["last_ai_selection"] = selection
    write_json(_settings_path(global_dir), settings)
    return settings


def last_ai_selection(global_dir: str) -> dict[str, str] | None:
    """Return the remembered AI provider/model selection, if one exists."""
    return load_global_settings(global_dir).get("last_ai_selection")
