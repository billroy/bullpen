"""Worker type registry and canonical slot helpers."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from server.model_aliases import normalize_model


VALID_WORKER_TYPES = {"ai", "shell", "eval"}
RUNTIME_FIELDS = {"task_queue", "state", "started_at"}


@dataclass(frozen=True)
class ViewerContext:
    can_edit: bool = True


class WorkerType:
    type_id = "unknown"

    def validate_config(self, slot):
        return []

    def default_icon(self):
        return "bot"

    def default_color(self):
        return None

    def runnable(self):
        return True


class AIWorkerType(WorkerType):
    type_id = "ai"

    def default_icon(self):
        return "bot"


class ShellWorkerType(WorkerType):
    type_id = "shell"

    def validate_config(self, slot):
        if not str(slot.get("command") or "").strip():
            return ["Shell workers require a command."]
        return []

    def default_icon(self):
        return "terminal"

    def default_color(self):
        return "neutral"


class EvalWorkerType(WorkerType):
    type_id = "eval"

    def validate_config(self, slot):
        return ["Eval workers are not yet implemented."]

    def default_icon(self):
        return "flask-conical"

    def runnable(self):
        return False


class UnknownWorkerType(WorkerType):
    def __init__(self, type_id):
        self.type_id = type_id

    def validate_config(self, slot):
        return [f"Worker type not installed: {self.type_id}"]

    def default_icon(self):
        return "circle-help"

    def runnable(self):
        return False


WORKER_TYPES = {
    "ai": AIWorkerType(),
    "shell": ShellWorkerType(),
    "eval": EvalWorkerType(),
}


def get_worker_type(type_id):
    type_id = str(type_id or "ai").strip() or "ai"
    return WORKER_TYPES.get(type_id, UnknownWorkerType(type_id))


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _default_cols(config):
    grid = config.get("grid", {}) if isinstance(config, dict) else {}
    cols = _safe_int(grid.get("cols", 4), 4)
    return cols if cols > 0 else 4


def _default_coord(index, config):
    cols = _default_cols(config)
    return index % cols, index // cols


def _normalize_env(env):
    if not isinstance(env, list):
        return []
    normalized = []
    for item in env:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        normalized.append({"key": key, "value": str(item.get("value") or "")})
    return normalized


def normalize_worker_slot(raw, *, index, config):
    """Return a canonical worker slot, preserving unknown fields."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None

    slot = copy.deepcopy(raw)
    type_id = slot.get("type")
    if not isinstance(type_id, str) or not type_id.strip():
        type_id = "ai"
    else:
        type_id = type_id.strip()
    slot["type"] = type_id

    default_col, default_row = _default_coord(index, config)
    slot["row"] = _safe_int(slot.get("row"), default_row)
    slot["col"] = _safe_int(slot.get("col"), default_col)
    slot["name"] = str(slot.get("name") or "Worker")
    slot["activation"] = str(slot.get("activation") or "on_drop")
    slot["disposition"] = str(slot.get("disposition") or "review")
    slot.setdefault("watch_column", None)
    slot["max_retries"] = max(0, _safe_int(slot.get("max_retries"), 1))
    slot.setdefault("trigger_time", None)
    slot.setdefault("trigger_interval_minutes", None)
    slot["trigger_every_day"] = bool(slot.get("trigger_every_day", False))
    slot.setdefault("last_trigger_time", None)
    slot["paused"] = bool(slot.get("paused", False))
    if not isinstance(slot.get("task_queue"), list):
        slot["task_queue"] = []
    slot["state"] = str(slot.get("state") or "idle")

    if type_id == "ai":
        slot["agent"] = str(slot.get("agent") or "claude")
        slot["model"] = normalize_model(slot["agent"], slot.get("model") or "claude-sonnet-4-6")
        slot["expertise_prompt"] = str(slot.get("expertise_prompt") or "")
        slot["use_worktree"] = bool(slot.get("use_worktree", False))
        slot["auto_commit"] = bool(slot.get("auto_commit", False))
        slot["auto_pr"] = bool(slot.get("auto_pr", False))
    elif type_id == "shell":
        slot["command"] = str(slot.get("command") or "")
        slot["cwd"] = str(slot.get("cwd") or "")
        slot["timeout_seconds"] = max(1, min(_safe_int(slot.get("timeout_seconds"), 60), 600))
        delivery = str(slot.get("ticket_delivery") or "stdin-json")
        if delivery not in ("stdin-json", "env-vars", "argv-json"):
            delivery = "stdin-json"
        slot["ticket_delivery"] = delivery
        slot["env"] = _normalize_env(slot.get("env"))

    return slot


def normalize_layout(layout, *, config):
    """Normalize every slot in a layout object."""
    if not isinstance(layout, dict):
        layout = {}
    normalized = dict(layout)
    raw_slots = normalized.get("slots", [])
    if not isinstance(raw_slots, list):
        raw_slots = []
    normalized["slots"] = [
        normalize_worker_slot(slot, index=i, config=config)
        for i, slot in enumerate(raw_slots)
    ]
    return normalized


def serialize_worker_slot(slot, *, viewer):
    """Serialize a slot for a client, redacting sensitive fields if needed."""
    if slot is None:
        return None
    out = copy.deepcopy(slot)
    if out.get("type") == "shell" and not viewer.can_edit:
        if "command" in out:
            out["command"] = "<redacted>"
        if isinstance(out.get("env"), list):
            redacted = []
            for item in out["env"]:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "")
                if key:
                    redacted.append({"key": key, "value": "<redacted>"})
            out["env"] = redacted
    return out


def serialize_layout(layout, *, viewer, config=None):
    if config is not None:
        layout = normalize_layout(layout, config=config)
    serialized = dict(layout if isinstance(layout, dict) else {})
    slots = serialized.get("slots", [])
    if not isinstance(slots, list):
        slots = []
    serialized["slots"] = [serialize_worker_slot(slot, viewer=viewer) for slot in slots]
    return serialized


def copy_worker_slot(slot, *, reset_runtime):
    """Copy a worker slot, optionally resetting runtime-only fields."""
    copied = copy.deepcopy(slot)
    if reset_runtime:
        copied["task_queue"] = []
        copied["state"] = "idle"
        copied["last_trigger_time"] = None
        copied["paused"] = False
        copied.pop("started_at", None)
    return copied
