"""Socket event handlers."""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import hashlib
import copy
from io import BytesIO
from datetime import datetime, timezone

from flask import request
from flask_socketio import emit, join_room, rooms

from server import tasks as task_mod
from server.archive_transport import (
    detect_import_archive_type,
    export_all_zip_bytes,
    export_workspace_zip_bytes,
    import_all_archive,
    import_workspace_archive,
)
from server import opencode_models
from server.file_browser import (
    FileBrowserError,
    build_file_tree,
    file_exists,
    read_binary_file,
    read_text_file,
    write_text_file,
)
from server.persistence import read_json, write_json, atomic_write
from server.profiles import create_profile, list_profiles
from server.teams import save_team, load_team, list_teams
from server.usage import (
    build_usage_entry,
    build_usage_update,
    extract_stream_usage_event,
    merge_usage_dicts,
    merge_usage_max,
)
from server.model_aliases import normalize_model
from server.global_settings import last_ai_selection, load_global_settings, remember_ai_selection
from server import workers as worker_mod
from server import service_worker as service_worker_mod
from server import values as value_mod
from server.workers import _terminate_proc
from server.transfer import TransferError, transfer_worker
from server.locks import write_lock as _write_lock
from server import mcp_auth
from server.bento_carrier import BentoCarrierError, inspect_bento
from server.bento_workers import (
    BULLPEN_BENTO_MIMETYPE,
    BULLPEN_PROFILE_ID,
    apply_worker_bento,
    apply_worker_fragments_to_layout,
    build_worker_bento,
    copy_worker_for_fragment,
    preview_worker_bento,
    worker_export_name as _bento_worker_export_name,
)
from server.bento_tickets import (
    apply_ticket_bento,
    apply_ticket_fragments,
    build_ticket_bento,
    load_manifest as _bento_load_manifest,
    preview_ticket_bento,
)
from server.workspace_manager import ensure_within_projects_root, projects_root, resolve_project_path
from server.prompt_hardening import (
    TRUST_MODE_UNTRUSTED,
    harden_agent_argv,
    normalize_trust_mode,
    render_chat_trust_instructions,
    render_untrusted_text_block,
)
from server.templates import raw_value_text
from server.validation import (
    ValidationError, validate_task_create, validate_task_update,
    validate_id, validate_slot, validate_coord, validate_worker_configure,
    validate_payload_size, validate_config_update, validate_worker_move,
    validate_worker_move_group, validate_worker_paste_group, validate_worker_slots,
    validate_layout_update, validate_team_name, validate_terminal_id,
    validate_terminal_input, validate_terminal_size,
)
from server.worker_types import (
    NOTIFICATION_KOKORO_VOICES,
    NOTIFICATION_SPEECH_ENGINES,
    ViewerContext,
    copy_worker_slot,
    get_worker_type,
    normalize_layout,
    normalize_worker_slot,
    serialize_layout,
)


VALUE_TRIGGER_CONDITION_OPERATORS = {"any", "contains", "<", "<=", "==", ">", ">="}
VALUE_TRIGGER_RELATIONAL_OPERATORS = {"<", "<=", "==", ">", ">="}


def _condition_result(operator, configured_value, *, matched, coerced_value=None, coerced_value_type=None, error=None):
    return {
        "matched": bool(matched),
        "operator": operator,
        "configured_value": configured_value,
        "coerced_value": coerced_value,
        "coerced_value_type": coerced_value_type,
        "error": error,
    }


def _compare_values(left, operator, right):
    if operator == "==":
        return left == right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    return False


def _value_trigger_condition_matches(value_event, worker):
    """Evaluate a value-change worker's condition against a value event."""
    operator = str((worker or {}).get("value_trigger_condition_operator") or "any").strip().lower()
    if operator not in VALUE_TRIGGER_CONDITION_OPERATORS:
        operator = "any"
    configured_value = str((worker or {}).get("value_trigger_condition_value") or "").strip()
    if operator == "any":
        return _condition_result("any", "", matched=True)

    new_value_type = str((value_event or {}).get("new_value_type") or "").strip().lower()
    new_value = (value_event or {}).get("new_value")
    if operator == "contains":
        if new_value_type not in {"number", "string"}:
            return _condition_result(
                operator,
                configured_value,
                matched=False,
                coerced_value=configured_value,
                coerced_value_type="string",
                error=f"unsupported value type: {new_value_type or 'unknown'}",
            )
        value_text = raw_value_text(new_value)
        return _condition_result(
            operator,
            configured_value,
            matched=configured_value in value_text,
            coerced_value=configured_value,
            coerced_value_type="string",
        )

    if operator not in VALUE_TRIGGER_RELATIONAL_OPERATORS:
        return _condition_result(operator, configured_value, matched=False, error="unsupported operator")

    if new_value_type == "number":
        parsed = value_mod.parse_plain_number(configured_value)
        if parsed is None:
            return _condition_result(
                operator,
                configured_value,
                matched=False,
                error="comparison value is not a valid number",
            )
        return _condition_result(
            operator,
            configured_value,
            matched=_compare_values(new_value, operator, parsed),
            coerced_value=parsed,
            coerced_value_type="number",
        )

    if new_value_type == "string":
        return _condition_result(
            operator,
            configured_value,
            matched=_compare_values(raw_value_text(new_value), operator, configured_value),
            coerced_value=configured_value,
            coerced_value_type="string",
        )

    return _condition_result(
        operator,
        configured_value,
        matched=False,
        error=f"unsupported value type: {new_value_type or 'unknown'}",
    )


_CLAUDE_MCP_READY_STATES = {"connected", "ready", "ok"}
_CLAUDE_MCP_PENDING_STATES = {"pending", "connecting", "initializing", "starting"}
_CLAUDE_MCP_STARTUP_RETRIES = 3
_CLAUDE_MCP_STARTUP_RETRY_BASE_DELAY = 0.75
_AI_COPY_FIELDS = {
    "type", "row", "col", "profile", "name", "agent", "model", "activation",
    "disposition", "watch_column", "expertise_prompt", "trust_mode", "max_retries",
    "use_worktree", "auto_commit", "auto_pr", "trigger_time",
    "trigger_interval_minutes", "trigger_every_day", "last_trigger_time",
    "paused", "task_queue", "state", "color", "avatar",
}
_DEFAULT_CHAT_TIMEOUT_SECONDS = 60
_MAX_CHAT_TIMEOUT_SECONDS = 3600
_MAX_NOTIFICATION_SPEECH_TEXT_LENGTH = 800


def _chat_timeout_seconds(bp_dir):
    try:
        config = read_json(os.path.join(bp_dir, "config.json"))
    except Exception:
        config = {}
    try:
        timeout = int(config.get("chat_timeout_seconds", _DEFAULT_CHAT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        timeout = _DEFAULT_CHAT_TIMEOUT_SECONDS
    return max(1, min(timeout, _MAX_CHAT_TIMEOUT_SECONDS))


def _clamp_float(value, default, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(number, high))


def _normalize_direct_speech_payload(data):
    text = str((data or {}).get("text") or "").strip()
    if not text:
        raise ValidationError("notification:speak requires text")
    text = text[:_MAX_NOTIFICATION_SPEECH_TEXT_LENGTH]

    engine = str((data or {}).get("engine") or "kokoro").strip().lower()
    if engine not in NOTIFICATION_SPEECH_ENGINES:
        raise ValidationError(f"Invalid speech engine: {engine}")

    voice = str((data or {}).get("voice") or "").strip()[:200]
    if engine == "kokoro" and voice and voice not in NOTIFICATION_KOKORO_VOICES:
        raise ValidationError(f"Invalid Kokoro voice: {voice}")

    created_at = _now_iso()
    return {
        "id": f"mcp_speech_{int(time.time() * 1000)}",
        "ephemeral": True,
        "slot": "mcp",
        "worker": {
            "name": "MCP speech",
            "type": "notification",
        },
        "ticket": {
            "id": "",
            "title": text,
        },
        "channels": {
            "toast": {
                "enabled": False,
                "text": "",
                "variant": "stage",
                "duration_ms": 6000,
            },
            "speech": {
                "enabled": True,
                "text": text,
                "voice": voice,
                "engine": engine,
                "rate": _clamp_float((data or {}).get("rate"), 1.0, 0.5, 2.0),
                "volume": _clamp_float((data or {}).get("volume"), 1.0, 0.0, 1.0),
            },
            "sound": {
                "enabled": False,
                "effect": "done",
                "repeat_count": 1,
                "gap_ms": 250,
                "volume": 1.0,
            },
            "flash": {
                "enabled": False,
                "sequence": [],
                "opacity": 0.35,
            },
        },
        "policy": {
            "cooldown_ms": 0,
            "dedupe_window_ms": 0,
        },
        "created_at": created_at,
    }


def _remember_ai_selection(app, agent, model):
    settings = remember_ai_selection(app.config["manager"].global_dir, agent, model)
    emit("global:settings", settings, to="authenticated", namespace="/")
    return settings


def _harden_live_agent_argv(provider, argv):
    """Apply Live Agent safety hardening for provider-specific runs."""
    return harden_agent_argv(provider, argv, trust_mode=TRUST_MODE_UNTRUSTED, chat=True)


def _build_chat_prompt(history, message):
    parts = [
        "You are a Bullpen project assistant. You have MCP tools for managing tickets:",
        "- list_tickets: List tickets, optionally filtered by status.",
        "- list_tasks: Alias for list_tickets.",
        "- list_tickets_by_title: List tickets by approximate title match.",
        "- create_ticket: Create a new ticket.",
        "- update_ticket: Update an existing ticket's fields.",
        "",
        "Some clients expose these tools with a namespace, for example "
        "`mcp__bullpen__update_ticket` or `mcp_bullpen_update_ticket`. Use the "
        "available Bullpen ticket tool with the matching base name.",
        "",
        "IMPORTANT: Always use these MCP tools for ticket operations. Do NOT read "
        ".bullpen/tasks/ files directly — those are internal storage. The MCP tools "
        "ensure the UI updates in real time.",
        "",
        render_chat_trust_instructions(),
    ]
    if history:
        turns = []
        for idx, turn in enumerate(history, start=1):
            role = "User" if turn["role"] == "user" else "Assistant"
            turns.append(f"[{idx}] {role}:\n{turn['content']}")
        parts.append(render_untrusted_text_block(
            "Conversation History",
            "\n\n".join(turns),
            "CHAT_HISTORY",
        ))
    parts.append(render_untrusted_text_block("Current User Message", message, "CHAT_USER_MESSAGE"))
    return "\n\n".join([part for part in parts if part])


def _claude_mcp_startup_state(line):
    """Return tuple (state, message) for bullpen MCP startup line, or None.

    State values:
      - "ready": Bullpen MCP is connected and usable.
      - "pending": Bullpen MCP is still initializing and retry is appropriate.
      - "error": Bullpen MCP is unavailable/missing and this run should fail.
    """
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if obj.get("type") != "system" or obj.get("subtype") != "init":
        return None

    servers = obj.get("mcp_servers") or []
    bullpen = next((s for s in servers if s.get("name") == "bullpen"), None)
    if not bullpen:
        return ("error", "Bullpen MCP server was not loaded for this session.")

    status = str(bullpen.get("status", "")).lower()
    if status in _CLAUDE_MCP_READY_STATES:
        return ("ready", None)
    if status in _CLAUDE_MCP_PENDING_STATES:
        return ("pending", f"Bullpen MCP unavailable at startup (status: {status}). Please retry.")
    if status:
        return ("error", f"Bullpen MCP unavailable at startup (status: {status}). Please retry.")
    return ("error", "Bullpen MCP unavailable at startup (missing status). Please retry.")


def _classify_chat_provider_error(provider, *texts, model=None):
    """Return a user-facing message for known non-retryable provider failures."""
    provider = (provider or "").strip().lower()
    model = (model or "").strip()
    haystack = "\n".join([t for t in texts if isinstance(t, str)]).lower()
    if not haystack:
        return None

    if provider == "antigravity":
        if (
            "requested entity was not found" in haystack
            or "modelnotfound" in haystack
            or "model_not_found" in haystack
            or "model not found" in haystack
            or ("404" in haystack and "model" in haystack)
            or "invalid model" in haystack
            or "unknown model" in haystack
        ):
            if model:
                return (
                    f"Antigravity CLI did not accept model {model}. "
                    "Choose a listed Antigravity model or enter an exact model name from `agy models`."
                )
            return (
                "Antigravity CLI did not accept the selected model. "
                "Choose a listed Antigravity model or enter an exact model name from `agy models`."
            )
        if (
            "authentication" in haystack
            or "not authenticated" in haystack
            or "unauthorized" in haystack
            or "oauth" in haystack
            or "log in" in haystack
            or "login" in haystack
        ):
            return "Antigravity CLI is not authenticated. Authenticate with `agy` in a terminal and retry."
        if (
            "permission_denied" in haystack
            or "permission denied" in haystack
            or "forbidden" in haystack
            or ("403" in haystack and "permission" in haystack)
        ):
            return "Antigravity CLI reported permission denied for this request. Check the selected model and account access."
        if (
            "failed to install antigravity mcp plugin" in haystack
            or "plugin" in haystack and "mcp" in haystack and "failed" in haystack
            or "mcpservers" in haystack and "error" in haystack
        ):
            return "Antigravity could not load the Bullpen MCP plugin. Restart Bullpen and retry."

    return None


def _load_layout(bp_dir):
    layout = read_json(os.path.join(bp_dir, "layout.json"))
    try:
        config = read_json(os.path.join(bp_dir, "config.json"))
    except Exception:
        config = {}
    return normalize_layout(layout, config=config)


def _save_layout(bp_dir, layout):
    try:
        config = read_json(os.path.join(bp_dir, "config.json"))
    except Exception:
        config = {}
    normalized = normalize_layout(layout, config=config)
    layout.clear()
    layout.update(normalized)
    write_json(os.path.join(bp_dir, "layout.json"), layout)


def _safe_legacy_cols(config):
    grid = config.get("grid", {}) if isinstance(config, dict) else {}
    cols = grid.get("cols", 4)
    try:
        cols = int(cols)
    except (TypeError, ValueError):
        cols = 4
    return cols if cols > 0 else 4


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slot_coord(worker, index, cols):
    if isinstance(worker, dict) and "col" in worker and "row" in worker:
        try:
            return int(worker.get("col", 0)), int(worker.get("row", 0))
        except (TypeError, ValueError):
            pass
    return index % cols, index // cols


def _coord_occupied(layout, coord, ignore_slot=None, cols=4):
    for i, worker in enumerate(layout.get("slots", [])):
        if not worker or i == ignore_slot:
            continue
        col, row = _slot_coord(worker, i, cols)
        if col == coord["col"] and row == coord["row"]:
            return i
    return None


def _coord_occupancy_map(layout, cols=4):
    occupied = {}
    for i, worker in enumerate(layout.get("slots", [])):
        if not worker:
            continue
        occupied[_slot_coord(worker, i, cols)] = i
    return occupied


def _first_empty_slot(layout):
    slots = layout.setdefault("slots", [])
    for i, worker in enumerate(slots):
        if worker is None:
            return i
    slots.append(None)
    return len(slots) - 1


def _nearest_empty_coord(layout, start_col, start_row, ignore_slot=None, cols=4):
    col = int(start_col)
    row = int(start_row)
    while _coord_occupied(layout, {"col": col, "row": row}, ignore_slot, cols) is not None:
        col += 1
    return {"col": col, "row": row}


def _write_runtime_mcp_config(app, bp_dir):
    """Write the current server connection metadata for MCP helper processes."""
    manager = app.config["manager"]
    token = mcp_auth.ensure_workspace_runtime_config(
        bp_dir,
        host=app.config.get("host", "127.0.0.1"),
        port=app.config.get("port", 5000),
        disallowed_tokens=mcp_auth.workspace_token_set(manager.all_workspaces(), exclude_bp_dir=bp_dir),
    )
    app.config.setdefault("mcp_tokens_by_workspace", {})
    ws = next((workspace for workspace in manager.all_workspaces() if workspace.bp_dir == bp_dir), None)
    if ws:
        app.config["mcp_tokens_by_workspace"][ws.id] = token


def register_events(socketio, app):
    """Register all socket.io event handlers."""

    def _resolve(data):
        """Resolve workspaceId from event data, return (workspace_id, bp_dir)."""
        manager = app.config["manager"]
        ws_id = data.get("workspaceId") if isinstance(data, dict) else None
        from server.app import mcp_sid_workspace
        bound_ws_id = mcp_sid_workspace.get(request.sid)
        if bound_ws_id:
            if ws_id and ws_id != bound_ws_id:
                logging.warning(
                    "Ignoring MCP request for workspace %s from sid %s; bound to %s",
                    ws_id,
                    request.sid,
                    bound_ws_id,
                )
            ws_id = bound_ws_id
        if not ws_id:
            ws_id = app.config["startup_workspace_id"]
            if ws_id:
                logging.warning("_resolve() fallback to startup_workspace_id %s — caller sent no workspaceId", ws_id)
        if not ws_id:
            emit("error", {"message": "No active workspace. Add or select a project first."})
            return None, None
        try:
            return ws_id, manager.get_bp_dir(ws_id)
        except KeyError:
            emit("error", {"message": f"Unknown workspace: {ws_id}"})
            return None, None

    def _bound_mcp_workspace():
        from server.app import mcp_sid_workspace
        return mcp_sid_workspace.get(request.sid)

    def _forbid_mcp_project_admin(event_name):
        if not _bound_mcp_workspace():
            return False
        emit("error", {"message": f"{event_name} unavailable for MCP-authenticated clients"})
        return True

    def _ensure_workspace_membership(ws_id):
        """Ensure the current socket is joined to the target workspace room.

        Client-side project switches emit `project:join`, but the first action
        after a switch can race that join. Auto-join valid workspaces here so a
        transient room-membership race does not reject the action.
        """
        if not ws_id:
            emit("error", {"message": "Missing workspaceId"})
            return False
        if ws_id in rooms(request.sid):
            return True
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        if not ws:
            emit("error", {"message": f"Unknown workspace: {ws_id}"})
            return False
        join_room(ws_id)
        return True

    def _emit(event, payload, ws_id):
        """Emit an event with workspaceId attached, scoped to workspace room."""
        if isinstance(payload, dict):
            payload["workspaceId"] = ws_id
        socketio.emit(event, payload, to=ws_id)
        # layout:updated replaces the client-side slot objects. Re-broadcast
        # known service runtime state so running service cards do not appear to
        # stop after duplicate/move/configure operations.
        if event == "layout:updated":
            try:
                bp_dir = app.config["manager"].get_bp_dir(ws_id)
            except Exception:
                bp_dir = None
            if bp_dir:
                service_worker_mod.emit_workspace_states(bp_dir, ws_id, socketio=socketio)

    def _emit_workspace_layout(ws_id):
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        if not ws:
            return
        layout = read_json(os.path.join(ws.bp_dir, "layout.json"))
        config = read_json(os.path.join(ws.bp_dir, "config.json"))
        layout = serialize_layout(layout, viewer=ViewerContext(can_edit=True), config=config)
        _emit("layout:updated", layout, ws.id)

    def _emit_service_preview_error(data, ws_id, message):
        emit("service:preview:error", {
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
            "ok": False,
            "error": message,
        })

    def _emit_opencode_models_error(data, ws_id, message):
        emit("models:opencode:error", {
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
            "ok": False,
            "status": "error",
            "error": message,
            "models": [],
        })

    def _archive_tasks_by_status(bp_dir, status, ws_id):
        """Archive live tasks with a matching status and clean worker references."""
        task_ids = [
            task["id"]
            for task in task_mod.list_tasks(bp_dir)
            if task.get("status") == status
        ]
        for task_id in task_ids:
            worker_mod.yank_from_worker(bp_dir, task_id, socketio, ws_id)
            task_mod.archive_task(bp_dir, task_id)
        return task_ids

    def _default_service_command_source(fields, workspace_path):
        explicit = str(fields.get("command_source") or "").strip()
        if explicit:
            return explicit
        procfile_path = os.path.join(workspace_path, "Procfile")
        return "procfile" if os.path.isfile(procfile_path) else "manual"

    def _service_slot(data, event_name):
        try:
            return validate_slot(data or {}, max_slots=200)
        except ValidationError as e:
            emit("error", {"message": f"{event_name} {e}"})
            return None

    def with_lock(fn):
        """Execute fn under write lock, emit error on failure."""
        def wrapper(data):
            with _write_lock:
                try:
                    return fn(data)
                except ValidationError as e:
                    emit("error", {"message": str(e)})
                except Exception as e:
                    logging.exception("Unhandled error in %s", fn.__name__)
                    emit("error", {"message": "An internal error occurred"})
        wrapper.__name__ = fn.__name__
        return wrapper

    def _normalized_worker_slots_for_bp(bp_dir):
        config = read_json(os.path.join(bp_dir, "config.json"))
        layout = normalize_layout(read_json(os.path.join(bp_dir, "layout.json")), config=config)
        slots = layout.get("slots", [])
        return slots if isinstance(slots, list) else []

    def _bento_fileobj(data):
        payload = (data or {}).get("file")
        if payload is None:
            payload = (data or {}).get("data")
        if payload is None:
            raise BentoCarrierError("Missing upload file", "missing-upload")
        if isinstance(payload, BytesIO):
            payload.seek(0)
            return payload
        if isinstance(payload, bytearray):
            return BytesIO(bytes(payload))
        if isinstance(payload, bytes):
            return BytesIO(payload)
        raise BentoCarrierError("Bento payload must be bytes", "invalid-upload")

    def _archive_fileobj(data):
        payload = (data or {}).get("file")
        if payload is None:
            payload = (data or {}).get("data")
        if payload is None:
            raise ValueError("Missing upload file")
        if isinstance(payload, BytesIO):
            payload.seek(0)
            return payload
        if isinstance(payload, bytearray):
            return BytesIO(bytes(payload))
        if isinstance(payload, bytes):
            return BytesIO(payload)
        raise ValueError("Archive payload must be bytes")

    def _build_bento_preview(fileobj, bp_dir):
        carrier_preview = inspect_bento(fileobj)
        if any(profile.get("id") == BULLPEN_PROFILE_ID for profile in carrier_preview.get("profiles", [])):
            fileobj.seek(0)
            manifest = _bento_load_manifest(fileobj)
            kind = _bento_kind(manifest)
            fileobj.seek(0)
            if kind in {"ticket", "ticket-bundle"}:
                return preview_ticket_bento(fileobj, bp_dir=bp_dir)
            if kind in {"worker", "worker-group"}:
                return preview_worker_bento(fileobj, bp_dir=bp_dir)
            raise BentoCarrierError("Unsupported Bullpen Bento package kind", "unsupported-kind")
        return carrier_preview

    def _bento_kind(manifest):
        declared = (manifest.get("bullpen") or {}).get("kind") if isinstance(manifest, dict) else None
        if declared:
            declared = str(declared)
        items = manifest.get("items") if isinstance(manifest, dict) else []
        item_types = [
            item.get("bullpen_type")
            for item in (items or [])
            if isinstance(item, dict) and item.get("bullpen_type")
        ]
        unique_types = set(item_types)
        inferred = None
        if unique_types == {"ticket"}:
            inferred = "ticket" if len(item_types) == 1 else "ticket-bundle"
        elif unique_types <= {"worker", "profile"} and "worker" in unique_types:
            worker_count = sum(1 for item_type in item_types if item_type == "worker")
            inferred = "worker" if worker_count == 1 else "worker-group"
        elif unique_types:
            inferred = "unsupported"

        ticket_kinds = {"ticket", "ticket-bundle"}
        worker_kinds = {"worker", "worker-group"}
        supported_kinds = ticket_kinds | worker_kinds
        if declared:
            if declared not in supported_kinds or inferred in {None, "unsupported"}:
                return "unsupported"
            if inferred and inferred != declared:
                return "unsupported"
            return declared
        return inferred

    def _bento_event_base(ws_id, data):
        base = {"workspaceId": ws_id}
        request_id = (data or {}).get("request_id") if isinstance(data, dict) else None
        if request_id:
            base["request_id"] = str(request_id)
        return base

    def _emit_bento_error(ws_id, data, error, code):
        emit("bento:error", {
            **_bento_event_base(ws_id, data),
            "ok": False,
            "error": error,
            "code": code,
        })

    @socketio.on("bento:preview")
    def on_bento_preview(data):
        ws_id, bp_dir = _resolve(data or {})
        if not ws_id:
            return
        try:
            fileobj = _bento_fileobj(data or {})
            preview = _build_bento_preview(fileobj, bp_dir)
            preview.update(_bento_event_base(ws_id, data))
            emit("bento:previewed", preview)
        except BentoCarrierError as e:
            _emit_bento_error(ws_id, data, e.message, e.code)

    @socketio.on("bento:export")
    def on_bento_export(data):
        ws_id, bp_dir = _resolve(data or {})
        if not ws_id:
            return
        manager = app.config["manager"]
        ws = manager.get(ws_id)
        if not ws:
            _emit_bento_error(ws_id, data, "Unknown workspace", "unknown-workspace")
            return
        kind = str((data or {}).get("kind") or "").strip()
        slots = _normalized_worker_slots_for_bp(bp_dir)
        try:
            if kind == "worker":
                slot = int((data or {}).get("slot"))
                if slot < 0 or slot >= len(slots) or not isinstance(slots[slot], dict):
                    _emit_bento_error(ws_id, data, "Unknown worker slot", "unknown-worker-slot")
                    return
                worker = slots[slot]
                filename = (
                    f"bullpen-worker-{_bento_worker_export_name(worker.get('name'), f'slot-{slot + 1}')}-"
                    f"{ws.id[:8]}.bento"
                )
                package = build_worker_bento(ws, [worker], kind="worker", selected_slots=[slot])
            elif kind == "worker-group":
                raw_slots = (data or {}).get("slots") or []
                if isinstance(raw_slots, str):
                    raw_slots = [part for part in raw_slots.split(",") if part.strip()]
                selected = []
                selected_indices = []
                seen = set()
                for raw in raw_slots:
                    slot = int(raw)
                    if slot in seen:
                        continue
                    seen.add(slot)
                    if slot < 0 or slot >= len(slots) or not isinstance(slots[slot], dict):
                        _emit_bento_error(ws_id, data, f"Unknown worker slot: {slot}", "unknown-worker-slot")
                        return
                    selected.append(slots[slot])
                    selected_indices.append(slot)
                if not selected:
                    _emit_bento_error(ws_id, data, "slots must include at least one worker", "missing-slots")
                    return
                workspace_name = _bento_worker_export_name(ws.name, "workspace")
                filename = f"bullpen-worker-group-{workspace_name}-{ws.id[:8]}.bento"
                package = build_worker_bento(ws, selected, kind="worker-group", selected_slots=selected_indices)
            elif kind == "ticket":
                task_id = str((data or {}).get("id") or "").strip()
                task = task_mod.read_task(bp_dir, task_id)
                if not task:
                    _emit_bento_error(ws_id, data, "Unknown ticket", "unknown-ticket")
                    return
                filename = (
                    f"bullpen-ticket-{_bento_worker_export_name(task.get('title'), task.get('id') or 'ticket')}-"
                    f"{ws.id[:8]}.bento"
                )
                package = build_ticket_bento(ws, [task], kind="ticket", selected_ids=[task["id"]])
            elif kind == "ticket-bundle":
                raw_ids = (data or {}).get("ids") or []
                if isinstance(raw_ids, str):
                    raw_ids = [part for part in raw_ids.split(",") if part.strip()]
                selected = []
                selected_ids = []
                seen = set()
                for raw in raw_ids:
                    task_id = str(raw or "").strip()
                    if not task_id or task_id in seen:
                        continue
                    seen.add(task_id)
                    task = task_mod.read_task(bp_dir, task_id)
                    if not task:
                        _emit_bento_error(ws_id, data, f"Unknown ticket: {task_id}", "unknown-ticket")
                        return
                    selected.append(task)
                    selected_ids.append(task_id)
                if not selected:
                    _emit_bento_error(ws_id, data, "ids must include at least one ticket", "missing-tickets")
                    return
                workspace_name = _bento_worker_export_name(ws.name, "workspace")
                filename = f"bullpen-ticket-bundle-{workspace_name}-{ws.id[:8]}.bento"
                package = build_ticket_bento(ws, selected, kind="ticket-bundle", selected_ids=selected_ids)
            else:
                _emit_bento_error(ws_id, data, "kind must be worker, worker-group, ticket, or ticket-bundle", "invalid-kind")
                return
        except (TypeError, ValueError):
            _emit_bento_error(ws_id, data, "Invalid Bento export request", "invalid-export-request")
            return
        emit("bento:exported", {
            **_bento_event_base(ws_id, data),
            "ok": True,
            "kind": kind,
            "filename": filename,
            "mimetype": BULLPEN_BENTO_MIMETYPE,
            "data": package.getvalue(),
        })

    @socketio.on("bento:import")
    def on_bento_import(data):
        ws_id, bp_dir = _resolve(data or {})
        if not ws_id:
            return
        try:
            fileobj = _bento_fileobj(data or {})
            inspect_bento(fileobj)
            fileobj.seek(0)
            manifest = _bento_load_manifest(fileobj)
            kind = _bento_kind(manifest)
            fileobj.seek(0)
            with _write_lock:
                if kind in {"ticket", "ticket-bundle"}:
                    result = apply_ticket_bento(
                        fileobj,
                        bp_dir=bp_dir,
                        target_status=(data or {}).get("target_status"),
                    )
                    tickets = result.get("tickets") or []
                    for task in tickets:
                        _emit("task:created", task, ws_id)
                elif kind in {"worker", "worker-group"}:
                    result = apply_worker_bento(
                        fileobj,
                        bp_dir=bp_dir,
                        placement=(data or {}).get("placement"),
                        mode=str((data or {}).get("mode") or "merge"),
                        approvals=(data or {}).get("approvals"),
                    )
                    layout = result.pop("layout")
                    _emit("layout:updated", layout, ws_id)
                else:
                    _emit_bento_error(ws_id, data, "Unsupported Bullpen Bento package kind", "unsupported-kind")
                    return
            result.update(_bento_event_base(ws_id, data))
            emit("bento:imported", result)
        except BentoCarrierError as e:
            _emit_bento_error(ws_id, data, e.message, e.code)

    @socketio.on("archive:export")
    def on_archive_export(data):
        payload = data or {}
        manager = app.config["manager"]
        kind = str(payload.get("kind") or "workspace").strip()
        ws_id, _bp_dir = _resolve(payload)
        if kind == "workspace":
            if not ws_id:
                return
            ws = manager.get(ws_id)
            if not ws:
                emit("archive:error", {
                    "workspaceId": ws_id,
                    "request_id": payload.get("request_id"),
                    "ok": False,
                    "error": "Unknown workspace",
                    "code": "unknown-workspace",
                })
                return
            package = export_workspace_zip_bytes(ws)
            filename = f"bullpen-workspace-{ws.name}-{ws.id[:8]}.zip"
        elif kind == "all":
            package = export_all_zip_bytes(manager)
            filename = f"bullpen-all-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.zip"
        else:
            emit("archive:error", {
                "workspaceId": ws_id,
                "request_id": payload.get("request_id"),
                "ok": False,
                "error": "kind must be workspace or all",
                "code": "invalid-kind",
            })
            return
        emit("archive:exported", {
            "workspaceId": ws_id,
            "request_id": payload.get("request_id"),
            "ok": True,
            "kind": kind,
            "filename": filename,
            "mimetype": "application/zip",
            "data": package.getvalue(),
        })

    @socketio.on("archive:import")
    def on_archive_import(data):
        payload = data or {}
        manager = app.config["manager"]
        kind = str(payload.get("kind") or "workspace").strip()
        ws_id, _bp_dir = _resolve(payload)
        try:
            fileobj = _archive_fileobj(payload)
            with _write_lock:
                if kind == "workspace":
                    if not ws_id:
                        return
                    ws = manager.get(ws_id)
                    if not ws:
                        emit("archive:error", {
                            "workspaceId": ws_id,
                            "request_id": payload.get("request_id"),
                            "ok": False,
                            "error": "Unknown workspace",
                            "code": "unknown-workspace",
                        })
                        return
                    result = import_workspace_archive(app, socketio, ws, fileobj)
                elif kind == "all":
                    result = import_all_archive(app, socketio, fileobj)
                else:
                    emit("archive:error", {
                        "workspaceId": ws_id,
                        "request_id": payload.get("request_id"),
                        "ok": False,
                        "error": "kind must be workspace or all",
                        "code": "invalid-kind",
                    })
                    return
            result["workspaceId"] = ws_id
            result["request_id"] = payload.get("request_id")
            result["kind"] = kind
            emit("archive:imported", result)
        except ValueError as e:
            emit("archive:error", {
                "workspaceId": ws_id,
                "request_id": payload.get("request_id"),
                "ok": False,
                "error": str(e),
                "code": "invalid-archive",
            })
        except Exception as e:
            emit("archive:error", {
                "workspaceId": ws_id,
                "request_id": payload.get("request_id"),
                "ok": False,
                "error": str(e),
                "code": "archive-import-failed",
            })

    @socketio.on("import:inspect")
    def on_import_inspect(data):
        payload = data or {}
        ws_id, bp_dir = _resolve(payload)
        if not ws_id:
            return
        try:
            fileobj = _archive_fileobj(payload)
            detected = detect_import_archive_type(fileobj)
            result = {
                "workspaceId": ws_id,
                "request_id": payload.get("request_id"),
                "ok": True,
                "import_type": detected.get("type"),
            }
            if detected.get("schema"):
                result["schema"] = detected["schema"]
            if detected.get("legacy"):
                result["legacy"] = True
            if detected.get("type") == "bento":
                fileobj.seek(0)
                preview = _build_bento_preview(fileobj, bp_dir)
                preview.update(_bento_event_base(ws_id, payload))
                result["preview"] = preview
                result["kind"] = preview.get("kind")
            emit("import:inspected", result)
        except BentoCarrierError as e:
            emit("import:error", {
                "workspaceId": ws_id,
                "request_id": payload.get("request_id"),
                "ok": False,
                "error": e.message,
                "code": e.code,
            })
        except ValueError as e:
            emit("import:error", {
                "workspaceId": ws_id,
                "request_id": payload.get("request_id"),
                "ok": False,
                "error": str(e),
                "code": "unknown-import-type",
            })

    @socketio.on("models:opencode")
    def on_opencode_models(data):
        ws_id, _bp_dir = _resolve(data or {})
        if not ws_id:
            return
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        if not ws:
            _emit_opencode_models_error(data, ws_id, "Unknown workspace")
            return
        provider = str((data or {}).get("provider") or "")
        refresh = bool((data or {}).get("refresh"))
        result = opencode_models.fetch_opencode_models(ws.path, provider=provider, refresh=refresh)
        if isinstance(result, dict):
            payload = dict(result)
        else:
            payload = {"status": "error", "error": "Invalid OpenCode model catalog response", "models": []}
        payload["workspaceId"] = ws_id
        payload["request_id"] = (data or {}).get("request_id")
        payload["ok"] = payload.get("status") != "error"
        emit("models:opencode:listed", payload)

    @socketio.on("commits:list")
    def on_commits_list(data):
        ws_id, _bp_dir = _resolve(data or {})
        if not ws_id:
            return
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        if not ws:
            emit("commits:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": "Unknown workspace",
            })
            return
        try:
            count = min(max(int((data or {}).get("count", 10)), 1), 50)
        except (ValueError, TypeError):
            count = 10
        try:
            offset = max(int((data or {}).get("offset", 0)), 0)
        except (ValueError, TypeError):
            offset = 0

        fmt = "%H\x1f%h\x1f%s\x1f%an\x1f%ai\x1f%b\x1e"
        try:
            result = subprocess.run(
                ["git", "log", f"-n{count}", f"--skip={offset}", f"--format={fmt}"],
                capture_output=True, text=True, cwd=ws.path, timeout=10,
            )
        except Exception as e:
            emit("commits:listed", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "commits": [],
                "has_more": False,
                "error": str(e),
            })
            return

        if result.returncode != 0:
            emit("commits:listed", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "commits": [],
                "has_more": False,
                "error": "Not a git repository",
            })
            return

        commits = []
        for record in result.stdout.split("\x1e"):
            record = record.strip()
            if not record:
                continue
            parts = record.split("\x1f", 5)
            if len(parts) < 5:
                continue
            commits.append({
                "hash": parts[0].strip(),
                "short_hash": parts[1].strip(),
                "subject": parts[2].strip(),
                "author": parts[3].strip(),
                "date": parts[4].strip(),
                "body": parts[5].strip() if len(parts) > 5 else "",
            })

        try:
            count_result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                capture_output=True, text=True, cwd=ws.path, timeout=5,
            )
            total = int(count_result.stdout.strip()) if count_result.returncode == 0 else 0
        except Exception:
            total = 0
        emit("commits:listed", {
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
            "ok": True,
            "commits": commits,
            "has_more": (offset + len(commits)) < total,
            "total": total,
        })

    @socketio.on("commits:diff")
    def on_commits_diff(data):
        ws_id, _bp_dir = _resolve(data or {})
        if not ws_id:
            return
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        commit_hash = str((data or {}).get("hash") or "").strip()
        if not ws:
            emit("commits:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": "Unknown workspace",
            })
            return
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_hash):
            emit("commits:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": "Invalid commit hash",
            })
            return
        try:
            result = subprocess.run(
                ["git", "show", "--format=", "--patch", "--no-color", commit_hash],
                capture_output=True, text=True, cwd=ws.path, timeout=10,
            )
        except Exception as e:
            emit("commits:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": str(e),
            })
            return
        if result.returncode != 0:
            emit("commits:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": "Commit not found",
            })
            return
        emit("commits:diffed", {
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
            "ok": True,
            "hash": commit_hash,
            "diff": result.stdout,
        })

    @socketio.on("files:list")
    def on_files_list(data):
        ws_id, _bp_dir = _resolve(data or {})
        if not ws_id:
            return
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        if not ws:
            emit("files:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": "Unknown workspace",
            })
            return
        emit("files:listed", {
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
            "ok": True,
            "tree": build_file_tree(ws.path),
        })

    @socketio.on("files:read")
    def on_files_read(data):
        ws_id, _bp_dir = _resolve(data or {})
        if not ws_id:
            return
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        if not ws:
            emit("files:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": "Unknown workspace",
            })
            return
        try:
            result = read_text_file(ws.path, str((data or {}).get("path") or ""))
        except FileBrowserError as e:
            emit("files:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": e.message,
                "status": e.status,
            })
            return
        result.update({
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
            "ok": True,
        })
        emit("files:read", result)

    @socketio.on("files:binary")
    def on_files_binary(data):
        ws_id, _bp_dir = _resolve(data or {})
        if not ws_id:
            return
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        if not ws:
            emit("files:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": "Unknown workspace",
            })
            return
        try:
            result = read_binary_file(ws.path, str((data or {}).get("path") or ""))
        except FileBrowserError as e:
            emit("files:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": e.message,
                "status": e.status,
            })
            return
        result.update({
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
            "ok": True,
        })
        emit("files:binary", result)

    @socketio.on("files:exists")
    def on_files_exists(data):
        ws_id, _bp_dir = _resolve(data or {})
        if not ws_id:
            return
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        if not ws:
            emit("files:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": "Unknown workspace",
            })
            return
        try:
            exists = file_exists(ws.path, str((data or {}).get("path") or ""))
        except FileBrowserError as e:
            emit("files:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": e.message,
                "status": e.status,
            })
            return
        emit("files:exists:result", {
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
            "ok": True,
            "path": str((data or {}).get("path") or ""),
            "exists": exists,
        })

    @socketio.on("files:write")
    def on_files_write(data):
        ws_id, _bp_dir = _resolve(data or {})
        if not ws_id:
            return
        manager = app.config["manager"]
        ws = manager.get_or_activate(ws_id)
        if not ws:
            emit("files:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": "Unknown workspace",
            })
            return
        try:
            result = write_text_file(
                ws.path,
                str((data or {}).get("path") or ""),
                str((data or {}).get("content") or ""),
                create=bool((data or {}).get("create")),
            )
        except FileBrowserError as e:
            emit("files:error", {
                "workspaceId": ws_id,
                "request_id": (data or {}).get("request_id"),
                "ok": False,
                "error": e.message,
                "status": e.status,
            })
            return
        result.update({
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
        })
        emit("files:written", result)
        socketio.emit("files:changed", {"workspaceId": ws_id}, to=ws_id)

    # --- Task events ---

    @socketio.on("task:create")
    @with_lock
    def on_task_create(data):
        ws_id, bp_dir = _resolve(data)
        if not _ensure_workspace_membership(ws_id):
            return
        clean = validate_task_create(data)
        kwargs = {
            "title": clean["title"],
            "description": clean["description"],
            "task_type": clean["type"],
            "priority": clean["priority"],
            "tags": clean["tags"],
        }
        if "status" in clean:
            kwargs["status"] = clean["status"]
        task = task_mod.create_task(bp_dir, **kwargs)
        _emit("task:created", task, ws_id)

        # Check if any on_queue workers are watching the new task's column
        if task.get("status"):
            worker_mod.check_watch_columns(
                bp_dir, task["status"], socketio, ws_id,
            )

    @socketio.on("task:update")
    @with_lock
    def on_task_update(data):
        ws_id, bp_dir = _resolve(data)
        if not _ensure_workspace_membership(ws_id):
            return
        task_id, fields = validate_task_update(data)

        # If status is changing, check whether the task is owned by a worker
        # and needs to be yanked out of its queue (+ process killed).
        #
        # Exception: if the caller is the MCP stdio client (i.e. an agent
        # updating its own ticket), do NOT yank. Otherwise the agent's own
        # `status=done` update would kill its own process before
        # _on_agent_success can run, skipping output logging and the
        # worker's configured disposition. The agent's terminal status
        # update is deferred for the same reason — the worker success path
        # owns the final status write.
        if "status" in fields:
            old_task = task_mod.read_task(bp_dir, task_id)
            old_status = old_task.get("status") if old_task else None
            new_status = fields["status"]
            from server.app import mcp_sids
            is_mcp_caller = request.sid in mcp_sids

            if old_status in ("assigned", "in_progress") and new_status not in ("assigned", "in_progress"):
                if is_mcp_caller:
                    # Do not move the ticket immediately while the worker's
                    # process is still alive. Record the requested final
                    # status so the worker success path can apply it after
                    # output logging and queue cleanup.
                    fields["worker_requested_status"] = new_status
                    fields.pop("status", None)
                else:
                    worker_mod.yank_from_worker(bp_dir, task_id, socketio, ws_id)
                    # Clear assignment since the task is leaving the worker system
                    fields["assigned_to"] = ""
                    fields["handoff_depth"] = 0
                    fields["worker_requested_status"] = ""

        task = task_mod.update_task(bp_dir, task_id, fields)
        _emit("task:updated", task, ws_id)

        # If status changed, check if any on_queue workers are watching that column
        if "status" in fields:
            worker_mod.check_watch_columns(
                bp_dir, fields["status"], socketio, ws_id,
            )

    @socketio.on("notification:speak")
    @with_lock
    def on_notification_speak(data):
        ws_id, _bp_dir = _resolve(data)
        if not _ensure_workspace_membership(ws_id):
            return {"ok": False, "error": "workspace unavailable"}
        try:
            payload = _normalize_direct_speech_payload(data)
        except ValidationError as e:
            emit("error", {"message": str(e)})
            return {"ok": False, "error": str(e)}
        payload["workspaceId"] = ws_id
        socketio.emit("notification:fire", payload, to=ws_id)
        return {
            "ok": True,
            "id": payload["id"],
            "engine": payload["channels"]["speech"]["engine"],
            "voice": payload["channels"]["speech"]["voice"],
            "text": payload["channels"]["speech"]["text"],
        }

    @socketio.on("task:delete")
    @with_lock
    def on_task_delete(data):
        ws_id, bp_dir = _resolve(data)
        task_id = validate_id(data)
        worker_mod.yank_from_worker(bp_dir, task_id, socketio, ws_id)
        task_mod.delete_task(bp_dir, task_id)
        _emit("task:deleted", {"id": task_id}, ws_id)

    @socketio.on("task:archive")
    @with_lock
    def on_task_archive(data):
        ws_id, bp_dir = _resolve(data)
        task_id = validate_id(data)
        worker_mod.yank_from_worker(bp_dir, task_id, socketio, ws_id)
        task_mod.archive_task(bp_dir, task_id)
        _emit("task:deleted", {"id": task_id}, ws_id)

    @socketio.on("task:archive-done")
    @with_lock
    def on_task_archive_done(data):
        ws_id, bp_dir = _resolve(data)
        archived = _archive_tasks_by_status(bp_dir, "done", ws_id)
        for task_id in archived:
            _emit("task:deleted", {"id": task_id}, ws_id)

    @socketio.on("task:archive-column")
    @with_lock
    def on_task_archive_column(data):
        ws_id, bp_dir = _resolve(data)
        status = str((data or {}).get("status", "")).strip()
        if not status or len(status) > 100:
            emit("error", {"message": "task:archive-column requires status"})
            return
        archived = _archive_tasks_by_status(bp_dir, status, ws_id)
        for task_id in archived:
            _emit("task:deleted", {"id": task_id}, ws_id)

    @socketio.on("task:clear_output")
    @with_lock
    def on_task_clear_output(data):
        ws_id, bp_dir = _resolve(data)
        task_id = validate_id(data)
        task = task_mod.clear_task_output(bp_dir, task_id)
        _emit("task:updated", task, ws_id)

    @socketio.on("task:list")
    @with_lock
    def on_task_list(data):
        ws_id, bp_dir = _resolve(data or {})
        scope = (data or {}).get("scope", "live")
        archived = str(scope).strip().lower() == "archived"
        tasks = task_mod.list_tasks(bp_dir, archived=archived)
        _emit("task:list", {"scope": "archived" if archived else "live", "tasks": tasks}, ws_id)

    @socketio.on("task:paste")
    @with_lock
    def on_task_paste(data):
        ws_id, bp_dir = _resolve(data or {})
        if not _ensure_workspace_membership(ws_id):
            return
        ticket = (data or {}).get("ticket")
        if ticket is None:
            ticket = (data or {}).get("task")
        try:
            result = apply_ticket_fragments(
                bp_dir,
                [ticket],
                target_status=(data or {}).get("target_status") or (data or {}).get("status"),
                kind="ticket-fragment",
            )
        except BentoCarrierError as e:
            emit("error", {"message": e.message, "code": e.code})
            return
        for task in result.get("tickets") or []:
            _emit("task:created", task, ws_id)
        emit("task:pasted", {**result, "workspaceId": ws_id})

    @socketio.on("task:paste_group")
    @with_lock
    def on_task_paste_group(data):
        ws_id, bp_dir = _resolve(data or {})
        if not _ensure_workspace_membership(ws_id):
            return
        tickets = (data or {}).get("tickets")
        if tickets is None:
            tickets = (data or {}).get("tasks")
        if tickets is None:
            tickets = [
                item.get("ticket") if isinstance(item, dict) and "ticket" in item else item
                for item in ((data or {}).get("items") or [])
            ]
        try:
            result = apply_ticket_fragments(
                bp_dir,
                tickets,
                target_status=(data or {}).get("target_status") or (data or {}).get("status"),
                kind="ticket-fragment-group",
            )
        except BentoCarrierError as e:
            emit("error", {"message": e.message, "code": e.code})
            return
        for task in result.get("tickets") or []:
            _emit("task:created", task, ws_id)
        emit("task:pasted", {**result, "workspaceId": ws_id})

    # --- Worker / Layout events ---

    @socketio.on("worker:add")
    @with_lock
    def on_worker_add(data):
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        coord = validate_coord(data, "coord")
        slot_index = validate_slot(data, max_slots=200) if coord is None else _first_empty_slot(layout)
        worker_type = str(data.get("type") or "").strip().lower()
        profile_id = data.get("profile")
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}

        if not worker_type:
            worker_type = "ai" if profile_id is not None else ""

        if worker_type not in ("ai", "shell", "service", "marker", "notification", "value"):
            emit("error", {"message": "worker:add requires a supported type"})
            return

        profile = None
        if worker_type == "ai":
            if profile_id is None:
                emit("error", {"message": "worker:add requires profile"})
                return
            from server.profiles import get_profile
            profile = get_profile(bp_dir, profile_id)
            if not profile:
                emit("error", {"message": f"Profile not found: {profile_id}"})
                return

        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = _safe_legacy_cols(config)
        if coord is None:
            row = slot_index // cols
            col = slot_index % cols
            coord = {"col": col, "row": row}
        else:
            occupied_slot = _coord_occupied(layout, coord, cols=cols)
            if occupied_slot is not None:
                emit("error", {"message": "Coordinate already occupied", "code": "coordinate_collision"})
                return
            row = coord["row"]
            col = coord["col"]

        existing_names = {s["name"] for s in layout["slots"] if s}

        def _unique_name(base):
            candidate = base
            suffix = 2
            while candidate in existing_names:
                candidate = f"{base} {suffix}"
                suffix += 1
            return candidate

        if worker_type == "ai":
            base_name = fields.get("name") or profile["name"]
            remembered = last_ai_selection(app.config["manager"].global_dir) or {}
            worker = {
                "type": "ai",
                "row": row,
                "col": col,
                "profile": profile_id,
                "name": _unique_name(base_name),
                "agent": remembered.get("agent") or profile.get("default_agent", "claude"),
                "model": remembered.get("model") or profile.get("default_model", "claude-sonnet-4-6"),
                "activation": profile.get("default_activation", "on_drop"),
                "disposition": profile.get("default_disposition", "review"),
                "watch_column": None,
                "expertise_prompt": profile.get("expertise_prompt", ""),
                "trust_mode": normalize_trust_mode(fields.get("trust_mode"), default=TRUST_MODE_UNTRUSTED),
                "max_retries": profile.get("default_max_retries", 1),
                "use_worktree": False,
                "auto_commit": False,
                "auto_pr": False,
                "trigger_time": None,
                "trigger_interval_minutes": None,
                "trigger_every_day": False,
                "last_trigger_time": None,
                "paused": False,
                "task_queue": [],
                "state": "idle",
            }
        elif worker_type == "shell":
            base_name = fields.get("name") or "Shell worker"
            worker = {
                "type": "shell",
                "row": row,
                "col": col,
                "name": _unique_name(str(base_name)),
                "activation": fields.get("activation", "on_drop"),
                "disposition": fields.get("disposition", "review"),
                "watch_column": None,
                "max_retries": int(fields.get("max_retries", 0) or 0),
                "trigger_time": None,
                "trigger_interval_minutes": None,
                "trigger_every_day": False,
                "last_trigger_time": None,
                "paused": False,
                "task_queue": [],
                "state": "idle",
                "command": str(fields.get("command", "") or ""),
                "cwd": str(fields.get("cwd", "") or ""),
                "timeout_seconds": int(fields.get("timeout_seconds", 60) or 60),
                "env": fields.get("env") if isinstance(fields.get("env"), list) else [],
                "ticket_delivery": fields.get("ticket_delivery", "stdin-json"),
            }
        elif worker_type == "service":
            base_name = fields.get("name") or "Service worker"
            workspace_path = app.config["manager"].get_workspace_path(ws_id)
            worker = {
                "type": "service",
                "row": row,
                "col": col,
                "name": _unique_name(str(base_name)),
                "activation": fields.get("activation", "manual"),
                "disposition": fields.get("disposition", "review"),
                "watch_column": None,
                "max_retries": int(fields.get("max_retries", 1) or 1),
                "trigger_time": None,
                "trigger_interval_minutes": None,
                "trigger_every_day": False,
                "last_trigger_time": None,
                "paused": False,
                "task_queue": [],
                "state": "idle",
                "command": str(fields.get("command", "") or ""),
                "command_source": _default_service_command_source(fields, workspace_path),
                "procfile_process": str(fields.get("procfile_process", "web") or "web"),
                "port": fields.get("port"),
                "cwd": str(fields.get("cwd", "") or ""),
                "pre_start": str(fields.get("pre_start", "") or ""),
                "ticket_action": fields.get("ticket_action", "start-if-stopped-else-restart"),
                "startup_grace_seconds": int(fields.get("startup_grace_seconds", 2) or 2),
                "startup_timeout_seconds": int(fields.get("startup_timeout_seconds", 60) or 60),
                "health_type": fields.get("health_type", "none"),
                "health_url": str(fields.get("health_url", "") or ""),
                "health_command": str(fields.get("health_command", "") or ""),
                "health_interval_seconds": int(fields.get("health_interval_seconds", 5) or 5),
                "health_timeout_seconds": int(fields.get("health_timeout_seconds", 2) or 2),
                "health_failure_threshold": int(fields.get("health_failure_threshold", 3) or 3),
                "on_crash": fields.get("on_crash", "stay-crashed"),
                "stop_timeout_seconds": int(fields.get("stop_timeout_seconds", 5) or 5),
                "log_max_bytes": int(fields.get("log_max_bytes", 5 * 1024 * 1024) or 5 * 1024 * 1024),
                "env": fields.get("env") if isinstance(fields.get("env"), list) else [],
            }
        elif worker_type == "value":
            updated_at = _now_iso()
            worker = {
                "type": "value",
                "row": row,
                "col": col,
                "name": str(fields.get("name", "") or "").strip(),
                "value": fields.get("value", ""),
                "value_type": fields.get("value_type", "auto"),
                "format": fields.get("format") if isinstance(fields.get("format"), dict) else {"kind": "auto"},
                "save_history": bool(fields.get("save_history", False)),
                "icon": "equal",
                "color": "value",
                "updated_at": updated_at,
            }
            value_mod.append_value_history(worker, updated_at)
        else:  # marker or notification
            if worker_type == "marker":
                base_name = fields.get("name") or "Marker"
                worker = {
                    "type": "marker",
                    "row": row,
                    "col": col,
                    "name": _unique_name(str(base_name)),
                    "note": str(fields.get("note", "") or ""),
                    "activation": fields.get("activation", "on_drop"),
                    "disposition": fields.get("disposition", "review"),
                    "watch_column": None,
                    "max_retries": 0,
                    "trigger_time": None,
                    "trigger_interval_minutes": None,
                    "trigger_every_day": False,
                    "last_trigger_time": None,
                    "paused": False,
                    "task_queue": [],
                    "state": "idle",
                    "icon": "square-dot",
                    "color": "marker",
                }
            else:
                base_name = fields.get("name") or "Notification worker"
                worker = {
                    "type": "notification",
                    "row": row,
                    "col": col,
                    "name": _unique_name(str(base_name)),
                    "activation": fields.get("activation", "on_drop"),
                    "disposition": fields.get("disposition", "review"),
                    "watch_column": None,
                    "max_retries": 0,
                    "trigger_time": None,
                    "trigger_interval_minutes": None,
                    "trigger_every_day": False,
                    "last_trigger_time": None,
                    "paused": False,
                    "task_queue": [],
                    "state": "idle",
                    "notification": fields.get("notification") if isinstance(fields.get("notification"), dict) else {},
                    "icon": "bell-ring",
                    "color": "notification",
                }

        # Ensure slots list is large enough
        while len(layout["slots"]) <= slot_index:
            layout["slots"].append(None)

        layout["slots"][slot_index] = worker
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)
        if worker_type == "value":
            _fire_value_change_triggers(
                bp_dir, layout, slot_index, {},
                updated_at=worker.get("updated_at") or _now_iso(),
                changed_by="worker:add",
                ws_id=ws_id,
            )

    @socketio.on("worker:remove")
    @with_lock
    def on_worker_remove(data):
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        slot_index = data.get("slot")

        if slot_index is None or slot_index >= len(layout["slots"]):
            emit("error", {"message": "worker:remove requires valid slot"})
            return

        layout["slots"][slot_index] = None
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:remove_many")
    @with_lock
    def on_worker_remove_many(data):
        ws_id, bp_dir = _resolve(data)
        slots = validate_worker_slots(data)
        layout = _load_layout(bp_dir)

        for slot in slots:
            if slot >= len(layout["slots"]) or not layout["slots"][slot]:
                emit("error", {"message": "worker:remove_many requires occupied slots"})
                return

        for slot in slots:
            layout["slots"][slot] = None
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:transfer")
    def on_worker_transfer(data):
        if not isinstance(data, dict):
            emit("worker:transfer:error", {"ok": False, "error": "invalid transfer payload"})
            return

        manager = app.config["manager"]
        source_ws_id = data.get("source_workspace_id") or data.get("workspaceId")
        if not _ensure_workspace_membership(source_ws_id):
            return

        raw_slots = data.get("source_slots")
        if isinstance(raw_slots, list) and raw_slots:
            seen = set()
            slots = []
            for raw in raw_slots:
                try:
                    slot = int(raw)
                except (TypeError, ValueError):
                    emit("worker:transfer:error", {
                        "workspaceId": source_ws_id,
                        "ok": False,
                        "error": "source_slots must contain integers",
                    })
                    return
                if slot in seen:
                    continue
                seen.add(slot)
                slots.append(slot)
        else:
            try:
                slots = [int(data.get("source_slot"))]
            except (TypeError, ValueError):
                emit("worker:transfer:error", {
                    "workspaceId": source_ws_id,
                    "ok": False,
                    "error": "source_slot is required",
                })
                return

        results = []
        warnings = []
        try:
            for slot in slots:
                result = transfer_worker(
                    manager,
                    source_workspace_id=source_ws_id,
                    source_slot=slot,
                    dest_workspace_id=data.get("dest_workspace_id"),
                    dest_slot=data.get("dest_slot") if len(slots) == 1 else None,
                    mode=data.get("mode", "copy"),
                    copy_profile=bool(data.get("copy_profile", False)),
                )
                results.append(result)
                warnings.extend(result.get("warnings") or [])
        except TransferError as e:
            emit("worker:transfer:error", {
                "workspaceId": source_ws_id,
                "ok": False,
                "error": str(e),
                "status": e.status,
                "results": results,
            })
            return

        dest_ws_id = data.get("dest_workspace_id")
        if dest_ws_id:
            _emit_workspace_layout(dest_ws_id)
        if data.get("mode") == "move":
            _emit_workspace_layout(source_ws_id)

        emit("worker:transferred", {
            "workspaceId": source_ws_id,
            "ok": True,
            "count": len(results),
            "results": results,
            "warnings": warnings,
            "dest_workspace_id": dest_ws_id,
            "mode": data.get("mode", "copy"),
        })

    @socketio.on("worker:move")
    @with_lock
    def on_worker_move(data):
        ws_id, bp_dir = _resolve(data)
        from_slot, to_slot, to_coord = validate_worker_move(data)
        layout = _load_layout(bp_dir)
        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = _safe_legacy_cols(config)

        if from_slot >= len(layout["slots"]) or not layout["slots"][from_slot]:
            emit("error", {"message": "worker:move requires occupied source slot"})
            return

        if to_coord is not None:
            occupied_slot = _coord_occupied(layout, to_coord, ignore_slot=from_slot, cols=cols)
            if occupied_slot is not None:
                emit("error", {"message": "Coordinate already occupied", "code": "coordinate_collision"})
                return
            layout["slots"][from_slot]["col"] = to_coord["col"]
            layout["slots"][from_slot]["row"] = to_coord["row"]
            _save_layout(bp_dir, layout)
            _emit("layout:updated", layout, ws_id)
            return

        # Ensure slots list is large enough
        max_slot = max(from_slot, to_slot)
        while len(layout["slots"]) <= max_slot:
            layout["slots"].append(None)

        # Capture pre-swap coords so workers trade visual positions.
        # Without this, the swap recomputes col/row from slot index using the
        # legacy grid formula, obliterating any sparse coordinates the workers
        # were placed at.
        src = layout["slots"][from_slot]
        dst = layout["slots"][to_slot]
        src_col, src_row = _slot_coord(src, from_slot, cols)
        if dst:
            dst_col, dst_row = _slot_coord(dst, to_slot, cols)
        else:
            dst_col, dst_row = to_slot % cols, to_slot // cols

        layout["slots"][from_slot], layout["slots"][to_slot] = dst, src

        if layout["slots"][to_slot]:
            layout["slots"][to_slot]["col"] = dst_col
            layout["slots"][to_slot]["row"] = dst_row
        if layout["slots"][from_slot]:
            layout["slots"][from_slot]["col"] = src_col
            layout["slots"][from_slot]["row"] = src_row

        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:move_group")
    @with_lock
    def on_worker_move_group(data):
        ws_id, bp_dir = _resolve(data)
        moves = validate_worker_move_group(data)
        layout = _load_layout(bp_dir)
        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = _safe_legacy_cols(config)

        moving_slots = {move["slot"] for move in moves}
        for slot in moving_slots:
            if slot >= len(layout["slots"]) or not layout["slots"][slot]:
                emit("error", {"message": "worker:move_group requires occupied source slots"})
                return

        occupied_by_coord = _coord_occupancy_map(layout, cols=cols)
        for move in moves:
            coord = move["to_coord"]
            occupied_slot = occupied_by_coord.get((coord["col"], coord["row"]))
            if occupied_slot is not None and occupied_slot not in moving_slots:
                emit("error", {"message": "Coordinate already occupied", "code": "coordinate_collision"})
                return

        for move in moves:
            slot = move["slot"]
            coord = move["to_coord"]
            layout["slots"][slot]["col"] = coord["col"]
            layout["slots"][slot]["row"] = coord["row"]

        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:duplicate")
    @with_lock
    def on_worker_duplicate(data):
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        slot_index = data.get("slot")

        if slot_index is None or slot_index >= len(layout["slots"]):
            emit("error", {"message": "worker:duplicate requires valid slot"})
            return

        source = layout["slots"][slot_index]
        if not source:
            emit("error", {"message": "No worker in slot"})
            return

        # Find first empty slot
        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = _safe_legacy_cols(config)
        target = _first_empty_slot(layout)
        source_col, source_row = _slot_coord(source, slot_index, cols)
        target_coord = _nearest_empty_coord(layout, source_col + 1, source_row, cols=cols)

        # Generate unique name
        base_name = source["name"]
        existing_names = {s["name"] for s in layout["slots"] if s}
        candidate = f"{base_name} copy"
        suffix = 2
        while candidate in existing_names:
            candidate = f"{base_name} copy {suffix}"
            suffix += 1

        # Clone worker config, reset runtime state
        if str(source.get("type") or "ai") == "ai":
            clone = {k: v for k, v in source.items() if k in _AI_COPY_FIELDS}
        else:
            clone = source
        clone = copy_worker_slot(clone, reset_runtime=True)
        clone["row"] = target_coord["row"]
        clone["col"] = target_coord["col"]
        clone["name"] = candidate

        layout["slots"][target] = clone
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:duplicate_group")
    @with_lock
    def on_worker_duplicate_group(data):
        ws_id, bp_dir = _resolve(data)
        slots = validate_worker_slots(data)
        layout = _load_layout(bp_dir)
        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = _safe_legacy_cols(config)

        for slot in slots:
            if slot >= len(layout["slots"]) or not layout["slots"][slot]:
                emit("error", {"message": "worker:duplicate_group requires occupied slots"})
                return

        anchor_slot = slots[0]
        anchor_worker = layout["slots"][anchor_slot]
        anchor_col, anchor_row = _slot_coord(anchor_worker, anchor_slot, cols)
        members = []
        for slot in slots:
            worker = layout["slots"][slot]
            col, row = _slot_coord(worker, slot, cols)
            members.append({
                "slot": slot,
                "worker": worker,
                "offset_col": col - anchor_col,
                "offset_row": row - anchor_row,
            })

        target_col = anchor_col + 1
        target_row = anchor_row
        while True:
            candidate_coords = [
                {"col": target_col + m["offset_col"], "row": target_row + m["offset_row"]}
                for m in members
            ]
            if all(coord["col"] >= 0 and coord["row"] >= 0 for coord in candidate_coords):
                occupied = [
                    _coord_occupied(layout, coord, cols=cols)
                    for coord in candidate_coords
                ]
                if all(slot is None for slot in occupied):
                    break
            target_col += 1

        existing_names = {s["name"] for s in layout["slots"] if s and s.get("name")}

        def unique_copy_name(base_name):
            base = str(base_name or "Worker")
            candidate = f"{base} copy"
            suffix = 2
            while candidate in existing_names:
                candidate = f"{base} copy {suffix}"
                suffix += 1
            existing_names.add(candidate)
            return candidate

        for member, coord in zip(members, candidate_coords):
            source = member["worker"]
            if str(source.get("type") or "ai") == "ai":
                clone_source = {k: v for k, v in source.items() if k in _AI_COPY_FIELDS}
            else:
                clone_source = source
            clone = copy_worker_slot(clone_source, reset_runtime=True)
            clone["row"] = coord["row"]
            clone["col"] = coord["col"]
            clone["name"] = unique_copy_name(source.get("name"))
            target = _first_empty_slot(layout)
            layout["slots"][target] = clone

        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:paste")
    @with_lock
    def on_worker_paste(data):
        ws_id, bp_dir = _resolve(data)
        coord = validate_coord(data, "coord", required=True)
        source = data.get("worker") or {}
        if not isinstance(source, dict):
            emit("error", {"message": "worker:paste requires worker config"})
            return

        layout = _load_layout(bp_dir)
        config = read_json(os.path.join(bp_dir, "config.json"))
        try:
            result = apply_worker_fragments_to_layout(
                layout,
                [{"coord": coord, "worker": copy_worker_for_fragment(source)}],
                config=config,
                replace=bool(data.get("replace")),
            )
        except BentoCarrierError as e:
            emit("error", {"message": e.message, "code": e.code})
            return
        layout = result["layout"]
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:paste_group")
    @with_lock
    def on_worker_paste_group(data):
        ws_id, bp_dir = _resolve(data)
        items = validate_worker_paste_group(data)
        layout = _load_layout(bp_dir)
        config = read_json(os.path.join(bp_dir, "config.json"))
        fragments = [
            {"coord": item["coord"], "worker": copy_worker_for_fragment(item["worker"])}
            for item in items
        ]
        try:
            result = apply_worker_fragments_to_layout(layout, fragments, config=config)
        except BentoCarrierError as e:
            emit("error", {"message": e.message, "code": e.code})
            return
        layout = result["layout"]

        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

    @socketio.on("worker:configure")
    @with_lock
    def on_worker_configure(data):
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        slot_index, fields = validate_worker_configure(data, max_slots=200)

        if slot_index >= len(layout["slots"]):
            emit("error", {"message": "worker:configure requires valid slot"})
            return

        worker = layout["slots"][slot_index]
        if not worker:
            emit("error", {"message": "No worker in slot"})
            return

        value_write_old_slot = None
        if worker.get("type") == "value" and any(k in fields for k in ("value", "value_type")):
            value_write_old_slot = copy.deepcopy(worker)
        for k, v in fields.items():
            if k not in ("task_queue", "state"):
                worker[k] = v
        if worker.get("type") == "value" and any(k in fields for k in ("value", "value_type", "format")):
            updated_at = _now_iso()
            worker["updated_at"] = updated_at
            value_mod.append_value_history(worker, updated_at)
        config = read_json(os.path.join(bp_dir, "config.json"))
        layout["slots"][slot_index] = normalize_worker_slot(worker, index=slot_index, config=config)
        worker = layout["slots"][slot_index]
        if worker.get("type") == "ai" and any(k in fields for k in ("agent", "model")):
            _remember_ai_selection(app, worker.get("agent"), worker.get("model"))

        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)
        if value_write_old_slot is not None:
            _fire_value_change_triggers(
                bp_dir, layout, slot_index, value_write_old_slot,
                updated_at=worker.get("updated_at") or _now_iso(),
                changed_by="worker_configure",
                ws_id=ws_id,
            )

        # If activation or watch_column changed, check for unclaimed tasks
        if ("activation" in fields or "watch_column" in fields):
            if (worker.get("activation") == "on_queue"
                    and worker.get("watch_column")
                    and worker.get("state") == "idle"
                    and not worker.get("paused")):
                worker_mod.check_watch_columns(
                    bp_dir, worker["watch_column"], socketio, ws_id,
                )

    @socketio.on("worker:configure_many")
    @with_lock
    def on_worker_configure_many(data):
        ws_id, bp_dir = _resolve(data)
        slots = validate_worker_slots(data)
        _, fields = validate_worker_configure({"slot": slots[0], "fields": data.get("fields")}, max_slots=200)
        layout = _load_layout(bp_dir)

        for slot in slots:
            if slot >= len(layout["slots"]) or not layout["slots"][slot]:
                emit("error", {"message": "worker:configure_many requires occupied slots"})
                return

        config = read_json(os.path.join(bp_dir, "config.json"))
        changed_watch_columns = []
        for slot in slots:
            worker = layout["slots"][slot]
            for k, v in fields.items():
                if k not in ("task_queue", "state"):
                    worker[k] = v
            layout["slots"][slot] = normalize_worker_slot(worker, index=slot, config=config)
            worker = layout["slots"][slot]
            if worker.get("type") == "ai" and any(k in fields for k in ("agent", "model")):
                _remember_ai_selection(app, worker.get("agent"), worker.get("model"))
            if ("activation" in fields or "watch_column" in fields):
                if (worker.get("activation") == "on_queue"
                        and worker.get("watch_column")
                        and worker.get("state") == "idle"
                        and not worker.get("paused")):
                    changed_watch_columns.append(worker["watch_column"])

        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)

        for watch_column in changed_watch_columns:
            worker_mod.check_watch_columns(bp_dir, watch_column, socketio, ws_id)

    def _resolve_value_slot(layout, ref, cols):
        match = value_mod.find_value_by_ref(layout.get("slots", []), ref, cols=cols)
        if not match:
            emit("error", {"message": f"Value not found: {ref}"})
            return None
        return match

    def _value_slot_event_payload(slot, index, coord, old_slot, *, updated_at, changed_by):
        old_slot = old_slot if isinstance(old_slot, dict) else {}
        old_payload = value_mod.normalize_value_payload(
            old_slot.get("value", ""), old_slot.get("value_type", slot.get("value_type", "auto"))
        )
        new_payload = value_mod.normalize_value_payload(slot.get("value", ""), slot.get("value_type", "auto"))
        changed = (
            old_payload.get("value") != new_payload.get("value")
            or old_payload.get("resolved_value_type") != new_payload.get("resolved_value_type")
        )
        coord_ref = value_mod.coord_to_cell_ref(coord)
        event_seed = json.dumps(
            {
                "slot": index,
                "coord": coord_ref,
                "old": old_payload,
                "new": new_payload,
                "updated_at": updated_at,
                "changed_by": changed_by,
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha1(event_seed.encode("utf-8")).hexdigest()[:12]
        return {
            "event_id": f"value:{index}:{updated_at}:{digest}",
            "value_slot": index,
            "value_name": str(slot.get("name") or ""),
            "value_coord": coord_ref,
            "units": str(slot.get("unit") or ""),
            "old_value": old_payload.get("value"),
            "old_value_type": old_payload.get("resolved_value_type"),
            "new_value": new_payload.get("value"),
            "new_value_type": new_payload.get("resolved_value_type"),
            "changed": changed,
            "changed_at": updated_at,
            "changed_by": changed_by,
        }

    def _value_trigger_matches(value_event, worker):
        scope = str((worker or {}).get("value_trigger_scope") or "name").strip().lower()
        ref = str((worker or {}).get("value_trigger_ref") or "").strip()
        if scope == "any":
            return True
        if scope == "name":
            if not ref:
                return False
            return value_mod.value_name_key(ref) == value_mod.value_name_key(value_event.get("value_name"))
        if scope == "coord":
            coord = value_mod.parse_cell_ref(ref)
            if coord is None:
                return False
            return value_mod.coord_to_cell_ref(coord) == value_event.get("value_coord")
        return False

    def _parse_iso_seconds(value):
        try:
            return datetime.strptime(str(value or ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None

    def _value_trigger_in_cooldown(worker, now_dt):
        try:
            cooldown = int(worker.get("value_trigger_cooldown_seconds") or 0)
        except (TypeError, ValueError):
            cooldown = 0
        if cooldown <= 0:
            return False
        last = _parse_iso_seconds(worker.get("last_value_trigger_time"))
        if last is None:
            return False
        return (now_dt - last).total_seconds() < cooldown

    def _create_value_trigger_task(bp_dir, slot_index, worker, value_event, socketio, ws_id, condition_result=None):
        worker_name = worker.get("name", "Worker")
        value_label = value_event.get("value_name") or value_event.get("value_coord") or "value"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        scope = str(worker.get("value_trigger_scope") or "name")
        configured_ref = str(worker.get("value_trigger_ref") or "")
        condition_result = condition_result or _condition_result("any", "", matched=True)
        condition_line = ""
        if condition_result.get("operator") != "any":
            condition_line = (
                "\n"
                f"Condition: new value {condition_result.get('operator')} "
                f"{condition_result.get('configured_value')} (matched)\n"
            )
        title = f"[Auto] {worker_name} - value write {value_label} - {timestamp}"
        body = (
            f"Worker: {worker_name}\n"
            f"Worker type: {worker.get('type', 'ai')}\n"
            "Trigger kind: on_value_change\n"
            f"Workspace: {os.path.dirname(bp_dir)}\n\n"
            "Value written:\n"
            f"- Name: {value_event.get('value_name') or '(unnamed)'}\n"
            f"- Coordinate: {value_event.get('value_coord') or ''}\n"
            f"- Units: {value_event.get('units') or ''}\n"
            f"- Old value: {value_event.get('old_value')}\n"
            f"- New value: {value_event.get('new_value')}\n"
            f"- Changed: {str(bool(value_event.get('changed'))).lower()}\n"
            f"- Changed at: {value_event.get('changed_at')}\n"
            f"- Changed by: {value_event.get('changed_by')}\n"
            f"{condition_line}"
        )
        task = task_mod.create_task(
            bp_dir,
            title,
            description=body,
            task_type="chore",
            priority="normal",
            tags=["synthetic", "worker-run", "value-change"],
        )
        trigger_meta = {
            **value_event,
            "scope": scope,
            "configured_ref": configured_ref,
            "condition": condition_result,
        }
        task = task_mod.update_task(bp_dir, task["id"], {
            "synthetic_run": True,
            "trigger_kind": "on_value_change",
            "synthetic_run_key": f"{slot_index}:on_value_change:{value_event.get('event_id')}",
            "value_trigger": trigger_meta,
        })
        _emit("task:created", task, ws_id)
        worker_mod.assign_task(bp_dir, slot_index, task["id"], socketio, ws_id, suppress_auto_start=True)
        return task

    def _fire_value_change_triggers(bp_dir, layout, value_index, old_slot, *, updated_at, changed_by, ws_id):
        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = _safe_legacy_cols(config)
        value_slot = layout.get("slots", [])[value_index]
        coord = value_mod.value_coord(value_slot, index=value_index, cols=cols)
        if coord is None:
            return
        value_event = _value_slot_event_payload(value_slot, value_index, coord, old_slot, updated_at=updated_at, changed_by=changed_by)
        now_dt = _parse_iso_seconds(updated_at) or datetime.now(timezone.utc)
        slots_to_start = []
        touched_runtime = False
        for slot_index, worker in enumerate(layout.get("slots", [])):
            if not isinstance(worker, dict):
                continue
            if worker.get("activation") != "on_value_change":
                continue
            if worker.get("type") not in ("ai", "shell", "notification"):
                continue
            if not value_event["changed"] and not bool(worker.get("value_trigger_fire_on_noop", True)):
                continue
            if worker_mod.worker_start_blocked(bp_dir, worker)[0]:
                continue
            if _value_trigger_in_cooldown(worker, now_dt):
                continue
            if not _value_trigger_matches(value_event, worker):
                continue
            condition_result = _value_trigger_condition_matches(value_event, worker)
            if not condition_result.get("matched"):
                logging.debug(
                    "Value trigger condition did not match: slot=%s event=%s operator=%s configured_value=%r "
                    "value_type=%s error=%s",
                    slot_index,
                    value_event.get("event_id"),
                    condition_result.get("operator"),
                    condition_result.get("configured_value"),
                    value_event.get("new_value_type"),
                    condition_result.get("error"),
                )
                continue
            worker["last_value_trigger_time"] = updated_at
            touched_runtime = True
            layout["slots"][slot_index] = worker
            _save_layout(bp_dir, layout)
            _create_value_trigger_task(bp_dir, slot_index, worker, value_event, socketio, ws_id, condition_result)
            slots_to_start.append(slot_index)
            layout = _load_layout(bp_dir)
        if touched_runtime:
            _emit("layout:updated", layout, ws_id)
        for slot_index in slots_to_start:
            try:
                current = _load_layout(bp_dir).get("slots", [])
                queue = current[slot_index].get("task_queue", []) if slot_index < len(current) and current[slot_index] else []
                expected_task_id = queue[0] if queue else None
                worker_mod._defer_start_worker(bp_dir, slot_index, socketio, ws_id, expected_task_id=expected_task_id)
            except Exception:
                logging.exception("Failed to schedule value-change worker start")

    @socketio.on("value:set")
    @with_lock
    def on_value_set(data):
        data = data or {}
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = _safe_legacy_cols(config)
        ref = str(data.get("ref") or "").strip()
        if not ref:
            emit("error", {"message": "value:set requires ref"})
            return
        match = _resolve_value_slot(layout, ref, cols)
        if not match:
            return
        slot = match["slot"]
        old_slot = copy.deepcopy(slot)
        value_type = data.get("value_type", slot.get("value_type", "auto"))
        if value_mod.normalize_value_type(value_type) == "number" and not value_mod.is_plain_number(data.get("value")):
            emit("error", {"message": "value must be numeric"})
            return
        payload = value_mod.normalize_value_payload(data.get("value", ""), value_type)
        slot["value"] = payload["value"]
        slot["value_type"] = payload["value_type"]
        slot["resolved_value_type"] = payload["resolved_value_type"]
        if "unit" in data:
            slot["unit"] = value_mod.normalize_unit(data.get("unit"))
        updated_at = _now_iso()
        slot["updated_at"] = updated_at
        value_mod.append_value_history(slot, updated_at)
        layout["slots"][match["index"]] = normalize_worker_slot(slot, index=match["index"], config=config)
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)
        _fire_value_change_triggers(
            bp_dir, layout, match["index"], old_slot,
            updated_at=updated_at,
            changed_by="value:set",
            ws_id=ws_id,
        )

    @socketio.on("value:increment")
    @with_lock
    def on_value_increment(data):
        data = data or {}
        ws_id, bp_dir = _resolve(data)
        layout = _load_layout(bp_dir)
        config = read_json(os.path.join(bp_dir, "config.json"))
        cols = _safe_legacy_cols(config)
        ref = str(data.get("ref") or "").strip()
        if not ref:
            emit("error", {"message": "value:increment requires ref"})
            return
        match = _resolve_value_slot(layout, ref, cols)
        if not match:
            return
        slot = match["slot"]
        old_slot = copy.deepcopy(slot)
        if slot.get("resolved_value_type") != "number" or isinstance(slot.get("value"), bool):
            emit("error", {"message": f"Value is not numeric: {ref}"})
            return
        try:
            amount = float(data.get("amount", 1))
        except (TypeError, ValueError):
            emit("error", {"message": "amount must be numeric"})
            return
        current = slot.get("value")
        if not isinstance(current, (int, float)):
            emit("error", {"message": f"Value is not numeric: {ref}"})
            return
        next_value = current + amount
        if isinstance(current, int) and float(next_value).is_integer():
            next_value = int(next_value)
        payload = value_mod.normalize_value_payload(next_value, slot.get("value_type", "auto"))
        slot["value"] = payload["value"]
        slot["value_type"] = payload["value_type"]
        slot["resolved_value_type"] = payload["resolved_value_type"]
        updated_at = _now_iso()
        slot["updated_at"] = updated_at
        value_mod.append_value_history(slot, updated_at)
        layout["slots"][match["index"]] = normalize_worker_slot(slot, index=match["index"], config=config)
        _save_layout(bp_dir, layout)
        _emit("layout:updated", layout, ws_id)
        _fire_value_change_triggers(
            bp_dir, layout, match["index"], old_slot,
            updated_at=updated_at,
            changed_by="value:increment",
            ws_id=ws_id,
        )

    @socketio.on("layout:update")
    @with_lock
    def on_layout_update(data):
        ws_id, bp_dir = _resolve(data)
        grid = validate_layout_update(data)
        config = read_json(os.path.join(bp_dir, "config.json"))

        if grid is not None:
            config["grid"] = grid
            write_json(os.path.join(bp_dir, "config.json"), config)

        _emit("config:updated", config, ws_id)

    @socketio.on("config:update")
    @with_lock
    def on_config_update(data):
        ws_id, bp_dir = _resolve(data)
        sanitized = validate_config_update(data)
        config = read_json(os.path.join(bp_dir, "config.json"))

        for k, v in sanitized.items():
            config[k] = v

        write_json(os.path.join(bp_dir, "config.json"), config)
        _emit("config:updated", config, ws_id)

    def _set_worker_automation_paused(bp_dir, ws_id, paused):
        config = read_json(os.path.join(bp_dir, "config.json"))
        config["worker_automation_paused"] = bool(paused)
        write_json(os.path.join(bp_dir, "config.json"), config)
        _emit("config:updated", config, ws_id)
        return config

    def _resume_worker_automation(bp_dir, socketio, ws_id):
        layout = worker_mod._load_layout(bp_dir)
        watched_columns = {
            worker.get("watch_column")
            for worker in layout.get("slots", [])
            if worker
            and worker.get("activation") == "on_queue"
            and worker.get("watch_column")
            and worker.get("state") == "idle"
            and not worker.get("paused")
            and not worker.get("task_queue")
        }
        for column in watched_columns:
            worker_mod.check_watch_columns(bp_dir, column, socketio, ws_id)
        worker_mod.drain_runnable_queues(bp_dir, socketio, ws_id)

    def _available_workspace_targets():
        manager = app.config["manager"]
        targets = []
        for project in manager.list_visible_projects(include_path=False):
            if project.get("available") is False:
                continue
            ws = manager.get_or_activate(project.get("id"))
            if ws:
                targets.append(ws)
        return targets

    def _forbid_mcp_all_workspace_control(event_name):
        if not _bound_mcp_workspace():
            return False
        emit("error", {"message": f"{event_name} unavailable for MCP-authenticated clients"})
        return True

    @socketio.on("workers:pause_automation")
    @with_lock
    def on_workers_pause_automation(data):
        ws_id, bp_dir = _resolve(data)
        _set_worker_automation_paused(bp_dir, ws_id, True)
        _emit("toast", {
            "message": "Worker automation paused. Active workers will finish their current step before advancing.",
            "level": "info",
        }, ws_id)

    @socketio.on("workers:resume_automation")
    @with_lock
    def on_workers_resume_automation(data):
        ws_id, bp_dir = _resolve(data)
        _set_worker_automation_paused(bp_dir, ws_id, False)
        _resume_worker_automation(bp_dir, socketio, ws_id)
        _emit("toast", {
            "message": "Worker automation resumed.",
            "level": "info",
        }, ws_id)

    @socketio.on("workers:stop_line")
    @with_lock
    def on_workers_stop_line(data):
        ws_id, bp_dir = _resolve(data)
        _set_worker_automation_paused(bp_dir, ws_id, True)
        stopped = worker_mod.stop_line_workers(bp_dir, socketio, ws_id)
        _emit("toast", {
            "message": (
                f"Stop The Line: stopped {stopped} active worker"
                f"{'' if stopped == 1 else 's'} and paused automation."
            ),
            "level": "warning",
        }, ws_id)

    @socketio.on("workers:pause_all_automation")
    @with_lock
    def on_workers_pause_all_automation(data):
        if _forbid_mcp_all_workspace_control("workers:pause_all_automation"):
            return
        targets = _available_workspace_targets()
        if not targets:
            emit("error", {"message": "No available workspaces to pause."})
            return
        for ws in targets:
            _set_worker_automation_paused(ws.bp_dir, ws.id, True)
        emit("toast", {
            "message": f"Worker automation paused in {len(targets)} workspace{'' if len(targets) == 1 else 's'}.",
            "level": "info",
        })

    @socketio.on("workers:resume_all_automation")
    @with_lock
    def on_workers_resume_all_automation(data):
        if _forbid_mcp_all_workspace_control("workers:resume_all_automation"):
            return
        targets = _available_workspace_targets()
        if not targets:
            emit("error", {"message": "No available workspaces to resume."})
            return
        for ws in targets:
            _set_worker_automation_paused(ws.bp_dir, ws.id, False)
        for ws in targets:
            _resume_worker_automation(ws.bp_dir, socketio, ws.id)
        emit("toast", {
            "message": f"Worker automation resumed in {len(targets)} workspace{'' if len(targets) == 1 else 's'}.",
            "level": "info",
        })

    @socketio.on("workers:stop_all_lines")
    @with_lock
    def on_workers_stop_all_lines(data):
        if _forbid_mcp_all_workspace_control("workers:stop_all_lines"):
            return
        targets = _available_workspace_targets()
        if not targets:
            emit("error", {"message": "No available workspaces to stop."})
            return
        for ws in targets:
            _set_worker_automation_paused(ws.bp_dir, ws.id, True)
        stopped = 0
        for ws in targets:
            stopped += worker_mod.stop_line_workers(ws.bp_dir, socketio, ws.id)
        emit("toast", {
            "message": (
                f"Stop All Workspaces: stopped {stopped} active worker"
                f"{'' if stopped == 1 else 's'} and paused automation in "
                f"{len(targets)} workspace{'' if len(targets) == 1 else 's'}."
            ),
            "level": "warning",
        })

    @socketio.on("prompt:update")
    @with_lock
    def on_prompt_update(data):
        ws_id, bp_dir = _resolve(data)
        prompt_type = data.get("type")
        content = data.get("content", "")

        if prompt_type != "workspace":
            emit("error", {"message": "prompt:update requires type 'workspace'"})
            return

        path = os.path.join(bp_dir, "workspace_prompt.md")
        atomic_write(path, content)
        _emit("prompt:updated", {"type": prompt_type, "content": content}, ws_id)

    @socketio.on("profile:create")
    @with_lock
    def on_profile_create(data):
        ws_id, bp_dir = _resolve(data)
        profile = create_profile(bp_dir, data)
        profiles = list_profiles(bp_dir)
        _emit("profiles:updated", profiles, ws_id)

    # --- Team events ---

    @socketio.on("team:save")
    @with_lock
    def on_team_save(data):
        ws_id, bp_dir = _resolve(data)
        name = validate_team_name(data.get("name"))
        layout = _load_layout(bp_dir)
        save_team(bp_dir, name, layout)
        teams = list_teams(bp_dir)
        _emit("teams:updated", teams, ws_id)

    @socketio.on("team:load")
    @with_lock
    def on_team_load(data):
        ws_id, bp_dir = _resolve(data)
        name = validate_team_name(data.get("name"))
        team_layout = load_team(bp_dir, name)
        if not team_layout:
            emit("error", {"message": f"Team not found: {name}"})
            return
        _save_layout(bp_dir, team_layout)
        _emit("layout:updated", team_layout, ws_id)

    # --- Execution events ---

    @socketio.on("task:assign")
    @with_lock
    def on_task_assign(data):
        ws_id, bp_dir = _resolve(data)
        task_id = validate_id(data or {}, "task_id")
        slot = validate_slot(data or {}, max_slots=200)
        if not task_mod.read_task(bp_dir, task_id):
            emit("error", {"message": f"Task not found: {task_id}"})
            return
        try:
            worker_mod.assign_task(bp_dir, slot, task_id, socketio, ws_id)
        except ValueError as exc:
            emit("error", {"message": str(exc)})

    @socketio.on("worker:start")
    @with_lock
    def on_worker_start(data):
        ws_id, bp_dir = _resolve(data)
        slot = data.get("slot")
        if slot is None:
            emit("error", {"message": "worker:start requires slot"})
            return
        worker_mod.start_worker(bp_dir, slot, socketio, ws_id)

    @socketio.on("worker:stop")
    @with_lock
    def on_worker_stop(data):
        ws_id, bp_dir = _resolve(data)
        slot = data.get("slot")
        if slot is None:
            emit("error", {"message": "worker:stop requires slot"})
            return
        worker_mod.stop_worker(bp_dir, slot, socketio, ws_id)

    @socketio.on("worker:stop_many")
    @with_lock
    def on_worker_stop_many(data):
        ws_id, bp_dir = _resolve(data)
        slots = validate_worker_slots(data)
        layout = _load_layout(bp_dir)
        for slot in slots:
            if slot >= len(layout["slots"]) or not layout["slots"][slot]:
                emit("error", {"message": "worker:stop_many requires occupied slots"})
                return
        for slot in slots:
            worker_mod.stop_worker(bp_dir, slot, socketio, ws_id)

    @socketio.on("notification:complete")
    @with_lock
    def on_notification_complete(data):
        ws_id, bp_dir = _resolve(data)
        slot = data.get("slot")
        if slot is None:
            emit("error", {"message": "notification:complete requires slot"})
            return
        worker_mod.complete_notification_delivery(
            bp_dir,
            slot,
            data.get("delivery_id") or data.get("id"),
            data.get("task_id"),
            data.get("status", "complete"),
            data.get("error", ""),
            socketio,
            ws_id,
        )

    # --- Output streaming events ---

    @socketio.on("worker:output:request")
    def on_worker_output_request(data):
        ws_id, bp_dir = _resolve(data)
        slot = data.get("slot")
        entry = worker_mod.get_output_buffer(ws_id, slot)
        if entry:
            emit("worker:output:catchup", {
                "slot": slot,
                "lines": list(entry["buffer"]),
                "workspaceId": ws_id,
            })

    # --- Service worker events ---

    @socketio.on("service:preview")
    def on_service_preview(data):
        ws_id, bp_dir = _resolve(data or {})
        if not ws_id or not bp_dir:
            return
        try:
            slot = int((data or {}).get("slot"))
        except (TypeError, ValueError):
            _emit_service_preview_error(data, ws_id, "slot is required")
            return

        config = read_json(os.path.join(bp_dir, "config.json"))
        layout = normalize_layout(read_json(os.path.join(bp_dir, "layout.json")), config=config)
        slots = layout.get("slots", [])
        if slot < 0 or slot >= len(slots) or not slots[slot]:
            _emit_service_preview_error(data, ws_id, "Service worker slot not found")
            return

        worker = dict(slots[slot])
        if worker.get("type") != "service":
            _emit_service_preview_error(data, ws_id, "Selected worker is not a Service worker")
            return
        fields = (data or {}).get("fields") or {}
        if not isinstance(fields, dict):
            _emit_service_preview_error(data, ws_id, "fields must be an object")
            return
        for key, value in fields.items():
            if key not in {"task_queue", "state", "started_at"}:
                worker[key] = value
        worker = normalize_worker_slot(worker, index=slot, config=config)
        errors = get_worker_type("service").validate_config(worker)
        if errors:
            _emit_service_preview_error(data, ws_id, errors[0])
            return

        try:
            preview = service_worker_mod.resolve_service_preview(worker, os.path.dirname(bp_dir), slot, bp_dir=bp_dir)
        except ValueError as e:
            _emit_service_preview_error(data, ws_id, str(e))
            return
        suggested_port = None
        if worker.get("port") is None:
            suggested_port = service_worker_mod.suggest_service_port(layout, ignore_slot=slot)

        emit("service:previewed", {
            "workspaceId": ws_id,
            "request_id": (data or {}).get("request_id"),
            "ok": True,
            "cwd": preview["cwd"],
            "procfile_path": preview["procfile_path"],
            "command_source": preview["command_source"],
            "process_names": preview["process_names"],
            "selected_process": preview["selected_process"],
            "suggested_port": suggested_port,
            "raw_command": preview["raw_command"],
            "resolved_command": preview["resolved_command_redacted"],
            "warnings": preview["warnings"],
        })

    @socketio.on("service:start")
    def on_service_start(data):
        ws_id, bp_dir = _resolve(data)
        slot = _service_slot(data, "service:start")
        if slot is None:
            return
        service_worker_mod.start_service(bp_dir, ws_id, slot, socketio)

    @socketio.on("service:stop")
    def on_service_stop(data):
        ws_id, bp_dir = _resolve(data)
        slot = _service_slot(data, "service:stop")
        if slot is None:
            return
        service_worker_mod.stop_service(bp_dir, ws_id, slot, socketio)

    @socketio.on("service:restart")
    def on_service_restart(data):
        ws_id, bp_dir = _resolve(data)
        slot = _service_slot(data, "service:restart")
        if slot is None:
            return
        service_worker_mod.restart_service(bp_dir, ws_id, slot, socketio)

    @socketio.on("service:tail")
    def on_service_tail(data):
        ws_id, bp_dir = _resolve(data)
        slot = _service_slot(data, "service:tail")
        if slot is None:
            return
        service_worker_mod.tail_service(
            bp_dir, ws_id, slot, socketio,
            max_bytes=(data or {}).get("max_bytes", 65536),
        )

    # --- Terminal events ---

    def _terminal_manager():
        return app.config["terminal_manager"]

    def _terminal_workspace(data, event_name):
        if _forbid_mcp_project_admin(event_name):
            return None, None
        ws_id, _bp_dir = _resolve(data or {})
        if not _ensure_workspace_membership(ws_id):
            return None, None
        workspace_path = app.config["manager"].get_workspace_path(ws_id)
        if not workspace_path:
            emit("terminal:error", {
                "workspaceId": ws_id,
                "terminalId": (data or {}).get("terminalId"),
                "message": "Unknown workspace",
            })
            return None, None
        return ws_id, workspace_path

    def _emit_terminal_error(data, message):
        emit("terminal:error", {
            "workspaceId": (data or {}).get("workspaceId"),
            "terminalId": (data or {}).get("terminalId"),
            "message": message,
        })

    @socketio.on("terminal:create")
    def on_terminal_create(data):
        try:
            ws_id, workspace_path = _terminal_workspace(data, "terminal:create")
            if not ws_id:
                return
            terminal_id = validate_terminal_id(data or {})
            cols, rows = validate_terminal_size(data or {})
            payload = _terminal_manager().create(
                workspace_id=ws_id,
                terminal_id=terminal_id,
                owner_sid=request.sid,
                cwd=workspace_path,
                cols=cols,
                rows=rows,
            )
            emit("terminal:created", payload)
        except (ValidationError, ValueError) as e:
            _emit_terminal_error(data, str(e))
        except Exception:
            logging.exception("terminal:create failed")
            _emit_terminal_error(data, "Unable to start terminal")

    @socketio.on("terminal:input")
    def on_terminal_input(data):
        try:
            ws_id, _workspace_path = _terminal_workspace(data, "terminal:input")
            if not ws_id:
                return
            terminal_id = validate_terminal_id(data or {})
            _terminal_manager().write(
                workspace_id=ws_id,
                terminal_id=terminal_id,
                owner_sid=request.sid,
                data=validate_terminal_input(data or {}),
            )
        except (ValidationError, ValueError) as e:
            _emit_terminal_error(data, str(e))

    @socketio.on("terminal:resize")
    def on_terminal_resize(data):
        try:
            ws_id, _workspace_path = _terminal_workspace(data, "terminal:resize")
            if not ws_id:
                return
            terminal_id = validate_terminal_id(data or {})
            cols, rows = validate_terminal_size(data or {})
            _terminal_manager().resize(
                workspace_id=ws_id,
                terminal_id=terminal_id,
                owner_sid=request.sid,
                cols=cols,
                rows=rows,
            )
        except (ValidationError, ValueError) as e:
            _emit_terminal_error(data, str(e))

    @socketio.on("terminal:close")
    def on_terminal_close(data):
        try:
            ws_id, _workspace_path = _terminal_workspace(data, "terminal:close")
            if not ws_id:
                return
            terminal_id = validate_terminal_id(data or {})
            closed = _terminal_manager().close(
                workspace_id=ws_id,
                terminal_id=terminal_id,
                owner_sid=request.sid,
            )
            if not closed:
                emit("terminal:closed", {"workspaceId": ws_id, "terminalId": terminal_id})
        except ValidationError as e:
            _emit_terminal_error(data, str(e))

    @socketio.on("terminal:restart")
    def on_terminal_restart(data):
        try:
            ws_id, workspace_path = _terminal_workspace(data, "terminal:restart")
            if not ws_id:
                return
            terminal_id = validate_terminal_id(data or {})
            cols, rows = validate_terminal_size(data or {})
            payload = _terminal_manager().restart(
                workspace_id=ws_id,
                terminal_id=terminal_id,
                owner_sid=request.sid,
                cwd=workspace_path,
                cols=cols,
                rows=rows,
            )
            emit("terminal:created", payload)
        except (ValidationError, ValueError) as e:
            _emit_terminal_error(data, str(e))

    @socketio.on("terminal:list")
    def on_terminal_list(data):
        try:
            ws_id, _workspace_path = _terminal_workspace(data, "terminal:list")
            if not ws_id:
                return
            emit("terminal:list", {
                "workspaceId": ws_id,
                "terminals": _terminal_manager().list_sessions(
                    workspace_id=ws_id,
                    owner_sid=request.sid,
                ),
            })
        except ValidationError as e:
            _emit_terminal_error(data, str(e))

    # --- Project events ---

    def _activate_and_broadcast_project(manager, ws_id):
        ws = manager.get(ws_id)
        _write_runtime_mcp_config(app, ws.bp_dir)

        # The connection that added the project should immediately receive
        # future room-scoped events for it. Other clients join when selected.
        join_room(ws_id)

        # Start scheduler for new workspace
        from server.scheduler import Scheduler
        if not ws.scheduler:
            scheduler = Scheduler(ws.bp_dir, socketio, ws_id=ws_id)
            scheduler.start()
            ws.scheduler = scheduler

        # Reconcile new workspace
        from server.app import reconcile, load_state, sync_deploy_label_config
        sync_deploy_label_config(ws.bp_dir)
        reconcile(ws.bp_dir)

        # Send state for the new workspace to the requesting client
        state = load_state(ws.bp_dir, ws.path, workspace_display=ws.name)
        state["workspaceId"] = ws_id
        state["switchTo"] = True
        state["globalSettings"] = load_global_settings(manager.global_dir)
        emit("state:init", state)

        # Broadcast updated project list to authenticated clients
        socketio.emit("projects:updated", manager.list_visible_projects(include_path=False), to="authenticated")

    def _default_clone_parent(manager, data):
        root = (os.environ.get("BULLPEN_PROJECTS_ROOT") or "").strip()
        if root:
            return os.path.abspath(root)

        ws_id = data.get("workspaceId") if isinstance(data, dict) else None
        ws = manager.get_or_activate(ws_id) if ws_id else None
        if ws is None:
            active = manager.all_workspaces()
            ws = active[0] if active else None
        if ws is not None:
            return os.path.dirname(ws.path)
        return os.getcwd()

    @socketio.on("project:join")
    def on_project_join(data):
        manager = app.config["manager"]
        ws_id = data.get("workspaceId") if isinstance(data, dict) else None
        bound_ws_id = _bound_mcp_workspace()
        if bound_ws_id:
            if ws_id and ws_id != bound_ws_id:
                emit("error", {"message": f"MCP client is only authorized for workspace {bound_ws_id}"})
                return
            ws_id = bound_ws_id
        ws = manager.get_or_activate(ws_id) if ws_id else None
        if not ws:
            emit("error", {"message": "Unknown project"})
            return
        join_room(ws_id)

        from server.app import load_state, sync_deploy_label_config
        sync_deploy_label_config(ws.bp_dir)
        state = load_state(ws.bp_dir, ws.path, workspace_display=ws.name)
        state["workspaceId"] = ws_id
        state["globalSettings"] = load_global_settings(manager.global_dir)
        emit("state:init", state)
        _emit_chat_tabs(ws_id, sid=request.sid)

    @socketio.on("project:add")
    @with_lock
    def on_project_add(data):
        if _forbid_mcp_project_admin("project:add"):
            return
        manager = app.config["manager"]
        raw_path = data.get("path", "").strip()
        if not raw_path:
            emit("error", {"message": "project:add requires path"})
            return
        path = resolve_project_path(raw_path)
        try:
            ws_id = manager.register_project(path)
        except ValueError as e:
            emit("error", {"message": str(e)})
            return

        _activate_and_broadcast_project(manager, ws_id)

    @socketio.on("project:new")
    @with_lock
    def on_project_new(data):
        if _forbid_mcp_project_admin("project:new"):
            return
        manager = app.config["manager"]
        raw_path = data.get("path", "")
        if not raw_path.strip():
            emit("error", {"message": "project:new requires path"})
            return
        path = resolve_project_path(raw_path)

        # Match register_project traversal hardening.
        if ".." in path.split(os.sep):
            emit("error", {"message": f"Invalid path: {path}"})
            return
        try:
            ensure_within_projects_root(path)
        except ValueError as e:
            emit("error", {"message": str(e)})
            return

        if os.path.exists(path):
            if not os.path.isdir(path):
                emit("error", {"message": f"Path exists and is not a directory: {path}"})
                return
            if os.listdir(path):
                emit("error", {"message": f"Directory is not empty: {path}"})
                return
        else:
            try:
                os.makedirs(path, exist_ok=False)
            except OSError as e:
                emit("error", {"message": f"Failed to create directory: {e}"})
                return

        try:
            ws_id = manager.register_project(path)
        except ValueError as e:
            emit("error", {"message": str(e)})
            return

        _activate_and_broadcast_project(manager, ws_id)

    @socketio.on("project:clone")
    @with_lock
    def on_project_clone(data):
        if _forbid_mcp_project_admin("project:clone"):
            return
        manager = app.config["manager"]
        url = (data.get("url") or "").strip()
        if not url:
            emit("error", {"message": "project:clone requires a git URL"})
            return

        raw_path = (data.get("path") or "").strip()
        if raw_path:
            path = resolve_project_path(raw_path)
        else:
            repo_name = url.rstrip("/").rsplit("/", 1)[-1]
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]
            if not repo_name:
                emit("error", {"message": f"Cannot derive directory name from URL: {url}"})
                return
            path = os.path.abspath(os.path.join(_default_clone_parent(manager, data), repo_name))

        if ".." in path.split(os.sep):
            emit("error", {"message": f"Invalid path: {path}"})
            return
        try:
            ensure_within_projects_root(path)
        except ValueError as e:
            emit("error", {"message": str(e)})
            return

        if os.path.exists(path):
            emit("error", {"message": f"Path already exists: {path}"})
            return

        emit("project:clone:started", {"url": url, "path": path})
        try:
            subprocess.run(
                ["git", "clone", url, path],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.CalledProcessError as e:
            emit("error", {"message": f"git clone failed: {e.stderr.strip() or e.stdout.strip()}"})
            return
        except subprocess.TimeoutExpired:
            emit("error", {"message": "git clone timed out (5 min limit)"})
            return

        try:
            ws_id = manager.register_project(path)
        except ValueError as e:
            emit("error", {"message": str(e)})
            return

        emit("project:clone:succeeded", {"url": url, "path": path, "workspaceId": ws_id})
        _activate_and_broadcast_project(manager, ws_id)

    @socketio.on("project:remove")
    @with_lock
    def on_project_remove(data):
        if _forbid_mcp_project_admin("project:remove"):
            return
        manager = app.config["manager"]
        ws_id = data.get("workspaceId")
        if not ws_id:
            emit("error", {"message": "project:remove requires workspaceId"})
            return

        # Don't allow removing the startup workspace
        if ws_id == app.config["startup_workspace_id"]:
            emit("error", {"message": "Cannot remove the startup project"})
            return

        service_worker_mod.stop_workspace_services(ws_id, wait=True)
        app.config["terminal_manager"].close_workspace(ws_id)
        manager.remove_project(ws_id)
        with _chat_lock:
            _chat_tabs.pop(ws_id, None)
            stale_keys = [key for key in _chat_sessions if key[0] == ws_id]
            for key in stale_keys:
                _chat_sessions.pop(key, None)
                _chat_session_ts.pop(key, None)
                _chat_ticket_ids.pop(key, None)
        socketio.emit("project:removed", {"workspaceId": ws_id}, to="authenticated")
        socketio.emit("projects:updated", manager.list_visible_projects(include_path=False), to="authenticated")

    @socketio.on("project:list")
    def on_project_list(data=None):
        manager = app.config["manager"]
        emit("project:settings", {"projectsRoot": projects_root() or ""})
        bound_ws_id = _bound_mcp_workspace()
        if bound_ws_id:
            ws = manager.get_or_activate(bound_ws_id)
            emit("projects:updated", [ws.to_dict(include_path=False)] if ws else [])
            return
        emit("projects:updated", manager.list_visible_projects(include_path=False))

    @socketio.on("chat:tabs:request")
    def on_chat_tabs_request(data):
        ws_id, _ = _resolve(data or {})
        if not _ensure_workspace_membership(ws_id):
            return
        _evict_stale_chat_sessions()
        if not _chat_tabs.get(ws_id):
            default_session = f"chat-default-{ws_id}"
            _upsert_chat_tab(ws_id, default_session, label="Live Agent", tab_id=default_session)
        _emit_chat_tabs(ws_id, sid=request.sid)

    @socketio.on("chat:tab:open")
    def on_chat_tab_open(data):
        ws_id, _ = _resolve(data or {})
        if not _ensure_workspace_membership(ws_id):
            return
        session_id = (data or {}).get("sessionId")
        if not str(session_id or "").strip():
            emit("error", {"message": "chat:tab:open requires sessionId"})
            return
        _evict_stale_chat_sessions()
        _upsert_chat_tab(
            ws_id,
            session_id,
            label=(data or {}).get("label") or "Live Agent",
            tab_id=(data or {}).get("id"),
        )
        _emit_chat_tabs(ws_id)

    @socketio.on("chat:tab:close")
    def on_chat_tab_close(data):
        ws_id, _ = _resolve(data or {})
        if not _ensure_workspace_membership(ws_id):
            return
        session_id = (data or {}).get("sessionId")
        if not str(session_id or "").strip():
            emit("error", {"message": "chat:tab:close requires sessionId"})
            return
        _remove_chat_tab(ws_id, session_id)
        if not _chat_tabs.get(ws_id):
            default_session = f"chat-default-{ws_id}"
            _upsert_chat_tab(ws_id, default_session, label="Live Agent", tab_id=default_session)
        _emit_chat_tabs(ws_id)

    # --- Chat events ---

    # In-memory chat sessions: (workspaceId, sessionId) -> list of {role, content}
    _chat_sessions = {}
    _chat_session_ts = {}  # (workspaceId, sessionId) -> last activity timestamp
    _chat_lock = threading.Lock()
    _CHAT_SESSION_TTL = 86400  # 24 hours

    # (workspaceId, sessionId) -> ticket ID (created lazily on first message)
    _chat_ticket_ids = {}
    _chat_tabs = {}  # workspaceId -> list of {id, sessionId, label}

    def _chat_key(ws_id, session_id):
        return (ws_id, session_id)

    def _chat_tab_payload(ws_id):
        with _chat_lock:
            tabs = [dict(tab) for tab in _chat_tabs.get(ws_id, [])]
        return {"workspaceId": ws_id, "tabs": tabs}

    def _emit_chat_tabs(ws_id, sid=None):
        payload = _chat_tab_payload(ws_id)
        if sid:
            socketio.emit("chat:tabs", payload, to=sid)
            return
        socketio.emit("chat:tabs", payload, to=ws_id)

    def _upsert_chat_tab(ws_id, session_id, label=None, tab_id=None):
        session_id = str(session_id or "").strip()
        if not ws_id or not session_id:
            return False
        safe_label = str(label or "Live Agent").strip() or "Live Agent"
        safe_id = str(tab_id or session_id).strip() or session_id
        now = time.time()
        with _chat_lock:
            tabs = _chat_tabs.setdefault(ws_id, [])
            for tab in tabs:
                if tab.get("sessionId") == session_id:
                    if tab.get("label") != safe_label:
                        tab["label"] = safe_label
                    if tab.get("id") != safe_id:
                        tab["id"] = safe_id
                    _chat_session_ts[_chat_key(ws_id, session_id)] = now
                    return False
            tabs.append({"id": safe_id, "sessionId": session_id, "label": safe_label})
            _chat_session_ts[_chat_key(ws_id, session_id)] = now
        return True

    def _remove_chat_tab(ws_id, session_id):
        if not ws_id or not session_id:
            return False
        removed = False
        with _chat_lock:
            tabs = _chat_tabs.get(ws_id, [])
            kept = [tab for tab in tabs if tab.get("sessionId") != session_id]
            if len(kept) != len(tabs):
                removed = True
                if kept:
                    _chat_tabs[ws_id] = kept
                else:
                    _chat_tabs.pop(ws_id, None)
                key = _chat_key(ws_id, session_id)
                _chat_sessions.pop(key, None)
                _chat_session_ts.pop(key, None)
                _chat_ticket_ids.pop(key, None)
        return removed

    def _emit_chat(event, payload, ws_id):
        if not ws_id:
            return
        body = dict(payload or {})
        body["workspaceId"] = ws_id
        socketio.emit(event, body, to=ws_id)

    def _evict_stale_chat_sessions():
        cutoff = time.time() - _CHAT_SESSION_TTL
        with _chat_lock:
            stale = [key for key, ts in _chat_session_ts.items() if ts < cutoff]
            for key in stale:
                _chat_sessions.pop(key, None)
                _chat_session_ts.pop(key, None)
                _chat_ticket_ids.pop(key, None)
                ws_id, session_id = key
                tabs = _chat_tabs.get(ws_id, [])
                kept = [tab for tab in tabs if tab.get("sessionId") != session_id]
                if len(kept) != len(tabs):
                    if kept:
                        _chat_tabs[ws_id] = kept
                    else:
                        _chat_tabs.pop(ws_id, None)

    # Active chat subprocesses: (workspaceId, sessionId) -> proc
    _chat_processes = {}
    _chat_proc_lock = threading.Lock()

    def _run_chat(
        session_id,
        message,
        argv,
        adapter,
        response_collector,
        workspace=None,
        ws_id=None,
        bp_dir=None,
        model=None,
        timeout_seconds=None,
    ):
        """Run chat agent subprocess, emit streaming lines, then emit done."""
        if not ws_id:
            logging.error("Chat run missing workspace context for session %s", session_id)
            return
        try:
            timeout_seconds = int(timeout_seconds or _DEFAULT_CHAT_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout_seconds = _DEFAULT_CHAT_TIMEOUT_SECONDS
        timeout_seconds = max(1, min(timeout_seconds, _MAX_CHAT_TIMEOUT_SECONDS))
        # Extract temp MCP config path for cleanup (written by adapter.build_argv)
        mcp_config_path = None
        for i, arg in enumerate(argv):
            if arg == "--mcp-config" and i + 1 < len(argv):
                mcp_config_path = argv[i + 1]
                break
        try:
            max_attempts = _CLAUDE_MCP_STARTUP_RETRIES if adapter.name == "claude" else 1

            for attempt in range(max_attempts):
                collected = []
                pending_startup = False
                startup_error = None
                saw_ready = adapter.name != "claude"
                chat_usage = {}  # normalized token usage across stream events
                env_cleanup_path = None

                popen_kwargs = dict(
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                if workspace:
                    popen_kwargs["cwd"] = workspace
                if os.name == "nt":
                    popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                else:
                    popen_kwargs["start_new_session"] = True
                prepared_env = adapter.prepare_env(workspace, bp_dir=bp_dir)
                if isinstance(prepared_env, tuple):
                    popen_kwargs["env"], env_cleanup_path = prepared_env
                else:
                    popen_kwargs["env"] = prepared_env
                proc = None
                timer = None
                timed_out = [False]
                try:
                    proc = subprocess.Popen(argv, **popen_kwargs)
                    with _chat_proc_lock:
                        _chat_processes[_chat_key(ws_id, session_id)] = proc

                    def _watchdog():
                        if proc.poll() is None:
                            timed_out[0] = True
                            _terminate_proc(proc)

                    timer = threading.Timer(timeout_seconds, _watchdog)
                    timer.daemon = True
                    timer.start()

                    prompt = response_collector["prompt"]
                    try:
                        if adapter.prompt_via_stdin():
                            proc.stdin.write(prompt)
                        proc.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass

                    batch = []
                    batch_lock = threading.Lock()
                    last_emit = [time.time()]
                    force_fail_message = [None]
                    raw_stdout = []
                    raw_stderr = []

                    def _drain_stdout():
                        nonlocal pending_startup, startup_error, saw_ready, chat_usage
                        for line in proc.stdout:
                            raw_stdout.append(line)
                            if adapter.name == "claude":
                                startup = _claude_mcp_startup_state(line)
                                if startup:
                                    state, msg = startup
                                    if state == "ready":
                                        saw_ready = True
                                    elif state == "pending":
                                        pending_startup = True
                                        # Pending can be transient while Claude finishes MCP setup.
                                        continue
                                    else:
                                        startup_error = msg or "Bullpen MCP unavailable at startup."
                                        try:
                                            _terminate_proc(proc)
                                        except OSError:
                                            pass
                                        return
                            # Capture token usage from known provider stream events.
                            try:
                                obj = json.loads(line.strip())
                                chat_usage = merge_usage_dicts(
                                    chat_usage, extract_stream_usage_event(adapter.name, obj)
                                )
                            except (json.JSONDecodeError, AttributeError):
                                pass
                            display = adapter.format_stream_line(line)
                            if display is None:
                                continue
                            for dl in display.split("\n"):
                                collected.append(dl)
                                to_emit = None
                                with batch_lock:
                                    batch.append(dl)
                                    now = time.time()
                                    if now - last_emit[0] >= 0.2:
                                        to_emit = list(batch)
                                        batch.clear()
                                        last_emit[0] = now
                                if to_emit:
                                    _emit_chat("chat:output", {"sessionId": session_id, "lines": to_emit}, ws_id)

                    def _drain_stderr():
                        try:
                            for line in proc.stderr:
                                raw_stderr.append(line)
                                line = line.rstrip()
                                if line:
                                    logging.warning("chat agent stderr [%s]: %s", session_id, line)
                                    if force_fail_message[0] is None:
                                        force_fail_message[0] = _classify_chat_provider_error(
                                            adapter.name, line, model=model,
                                        )
                                    if force_fail_message[0] and not collected:
                                        try:
                                            _terminate_proc(proc)
                                        except OSError:
                                            pass
                        except Exception:
                            pass

                    t_err = threading.Thread(target=_drain_stderr, daemon=True)
                    t_err.start()
                    _drain_stdout()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        _terminate_proc(proc, force=True)
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            pass
                    if timer:
                        timer.cancel()
                    t_err.join(timeout=2)

                    if timed_out[0]:
                        unit = "second" if timeout_seconds == 1 else "seconds"
                        _emit_chat(
                            "chat:error",
                            {
                                "sessionId": session_id,
                                "message": f"Agent timed out after {timeout_seconds} {unit}.",
                            },
                            ws_id,
                        )
                        return

                    if startup_error:
                        _emit_chat("chat:error", {"sessionId": session_id, "message": startup_error}, ws_id)
                        return

                    if pending_startup and not saw_ready:
                        # Claude can remain "pending" for MCP in init while still producing
                        # useful output. Do not convert that transient state into a hard error.
                        logging.info(
                            "chat agent [%s] mcp still pending at init; not forcing chat:error",
                            session_id,
                        )

                    # Flush remaining batch
                    with batch_lock:
                        if batch:
                            _emit_chat("chat:output", {"sessionId": session_id, "lines": list(batch)}, ws_id)
                            batch.clear()

                    stdout = "".join(raw_stdout)
                    stderr = "".join(raw_stderr)
                    parsed = adapter.parse_output(stdout, stderr, proc.returncode)
                    parsed_output = (parsed.get("output") or "").strip()
                    if force_fail_message[0] and not collected and not parsed_output:
                        _emit_chat("chat:error", {"sessionId": session_id, "message": force_fail_message[0]}, ws_id)
                        return
                    if not parsed.get("success", False):
                        classified_error = _classify_chat_provider_error(
                            adapter.name,
                            parsed.get("error", ""),
                            parsed.get("output", ""),
                            stderr,
                            model=model,
                        )
                        error_message = classified_error or parsed.get("error") or "Agent run failed."
                        _emit_chat("chat:error", {"sessionId": session_id, "message": error_message}, ws_id)
                        return

                    full_response = "\n".join(collected).strip()
                    if not full_response:
                        if parsed_output:
                            parsed_lines = parsed_output.splitlines() or [parsed_output]
                            _emit_chat("chat:output", {"sessionId": session_id, "lines": parsed_lines}, ws_id)
                            full_response = parsed_output

                    # Update session history
                    with _chat_lock:
                        chat_key = _chat_key(ws_id, session_id)
                        if chat_key in _chat_sessions:
                            _chat_sessions[chat_key].append({"role": "user", "content": message})
                            _chat_sessions[chat_key].append({"role": "assistant", "content": full_response})

                    # Log chat exchange to a ticket
                    if ws_id and bp_dir:
                        try:
                            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                            agent_label = f"{adapter.name}/{model}" if model else adapter.name
                            turn_text = (
                                f"\n**[{now}] User:** {message}\n\n"
                                f"**[{now}] Agent ({agent_label}):**\n\n{full_response}\n"
                            )
                            usage_entry = build_usage_entry(
                                source="chat",
                                provider=adapter.name,
                                model=model,
                                usage=merge_usage_max(chat_usage, parsed.get("usage", {})),
                                occurred_at=now,
                            )

                            with _chat_lock:
                                chat_key = _chat_key(ws_id, session_id)
                                ticket_id = _chat_ticket_ids.get(chat_key)
                            if not ticket_id:
                                short_title = message[:57] + "..." if len(message) > 57 else message
                                task = task_mod.create_task(
                                    bp_dir,
                                    f"Chat: {short_title}",
                                    task_type="task",
                                    priority="normal",
                                    tags=["chat"],
                                    status="review",
                                )
                                updates = {"body": f"\n## Chat Transcript\n{turn_text}"}
                                if usage_entry:
                                    updates.update(build_usage_update(task, usage_entry))
                                task = task_mod.update_task(bp_dir, task["id"], updates)
                                with _chat_lock:
                                    _chat_ticket_ids[chat_key] = task["id"]
                                _emit("task:created", task, ws_id)
                            else:
                                task = task_mod.read_task(bp_dir, ticket_id)
                                if task:
                                    updates = {"body": (task.get("body") or "").rstrip() + "\n" + turn_text}
                                    if usage_entry:
                                        updates.update(build_usage_update(task, usage_entry))
                                    task = task_mod.update_task(bp_dir, ticket_id, updates)
                                    _emit("task:updated", task, ws_id)
                        except Exception:
                            logging.exception("Failed to log chat to ticket for session %s", session_id)

                    _emit_chat("chat:done", {"sessionId": session_id}, ws_id)
                    return
                finally:
                    if timer:
                        timer.cancel()
                    if env_cleanup_path:
                        try:
                            adapter.finalize_env(popen_kwargs.get("env"), env_cleanup_path)
                        except Exception:
                            logging.exception("adapter.finalize_env failed for %s", adapter.name)
                        shutil.rmtree(env_cleanup_path, ignore_errors=True)

        except Exception as e:
            logging.exception("Chat agent error for session %s", session_id)
            _emit_chat("chat:error", {"sessionId": session_id, "message": str(e)}, ws_id)
        finally:
            with _chat_proc_lock:
                _chat_processes.pop(_chat_key(ws_id, session_id), None)
            if mcp_config_path:
                try:
                    os.unlink(mcp_config_path)
                except OSError:
                    pass

    @socketio.on("chat:send")
    def on_chat_send(data):
        from server.agents import get_adapter as _get_adapter
        session_id = data.get("sessionId", "")
        provider = data.get("provider", "claude")
        model = data.get("model", "claude-sonnet-4-6")
        model = normalize_model(provider, model)
        message = (data.get("message") or "").strip()
        ws_id, bp_dir = _resolve(data)
        manager = app.config["manager"]
        if not _ensure_workspace_membership(ws_id):
            emit("chat:error", {"sessionId": session_id, "workspaceId": ws_id, "message": f"Unknown workspace: {ws_id}"})
            return
        if not manager.get_bp_dir(ws_id):
            emit("chat:error", {"sessionId": session_id, "workspaceId": ws_id, "message": f"Unknown workspace: {ws_id}"})
            return

        if not session_id or not message:
            emit("chat:error", {"sessionId": session_id, "workspaceId": ws_id, "message": "sessionId and message are required"})
            return
        if len(message) > 100_000:
            emit("chat:error", {"sessionId": session_id, "workspaceId": ws_id, "message": "Message too long"})
            return

        if str(provider or "").strip().lower() == "gemini":
            emit(
                "chat:error",
                {
                    "sessionId": session_id,
                    "workspaceId": ws_id,
                    "message": "Gemini CLI support has been removed. Choose Antigravity or another supported provider.",
                },
            )
            return

        adapter = _get_adapter(provider)
        if not adapter:
            emit("chat:error", {"sessionId": session_id, "workspaceId": ws_id, "message": f"Unknown provider: {provider}"})
            return
        if not adapter.available():
            emit("chat:error", {"sessionId": session_id, "workspaceId": ws_id, "message": adapter.unavailable_message()})
            return
        _remember_ai_selection(app, provider, model)

        _evict_stale_chat_sessions()
        added = _upsert_chat_tab(
            ws_id,
            session_id,
            label=(data or {}).get("label") or "Live Agent",
            tab_id=(data or {}).get("id") or session_id,
        )
        if added:
            _emit_chat_tabs(ws_id)
        _emit_chat(
            "chat:user",
            {"sessionId": session_id, "message": message, "senderSid": request.sid},
            ws_id,
        )

        # Build prompt with conversation history
        chat_key = _chat_key(ws_id, session_id)
        with _chat_lock:
            if chat_key not in _chat_sessions:
                _chat_sessions[chat_key] = []
            _chat_session_ts[chat_key] = time.time()
            history = list(_chat_sessions[chat_key])

        full_prompt = _build_chat_prompt(history, message)

        workspace = os.path.dirname(bp_dir)
        argv = adapter.build_argv(full_prompt, model, workspace, bp_dir=bp_dir)
        argv = _harden_live_agent_argv(provider, argv)

        response_collector = {"prompt": full_prompt}
        timeout_seconds = _chat_timeout_seconds(bp_dir)
        thread = threading.Thread(
            target=_run_chat,
            args=(session_id, message, argv, adapter, response_collector),
            kwargs={
                "workspace": workspace,
                "ws_id": ws_id,
                "bp_dir": bp_dir,
                "model": model,
                "timeout_seconds": timeout_seconds,
            },
            daemon=True,
        )
        thread.start()

    @socketio.on("chat:clear")
    def on_chat_clear(data):
        session_id = data.get("sessionId", "")
        ws_id = data.get("workspaceId") if isinstance(data, dict) else None
        if ws_id and not _ensure_workspace_membership(ws_id):
            return
        touched = set()
        with _chat_lock:
            if ws_id:
                chat_key = _chat_key(ws_id, session_id)
                _chat_sessions.pop(chat_key, None)
                _chat_session_ts.pop(chat_key, None)
                _chat_ticket_ids.pop(chat_key, None)
                touched.add(ws_id)
            else:
                for key in [key for key in _chat_sessions if key[1] == session_id]:
                    _chat_sessions.pop(key, None)
                    _chat_session_ts.pop(key, None)
                    _chat_ticket_ids.pop(key, None)
                    touched.add(key[0])
        if ws_id:
            _emit_chat("chat:cleared", {"sessionId": session_id}, ws_id)
            return
        for touched_ws_id in touched:
            _emit_chat("chat:cleared", {"sessionId": session_id}, touched_ws_id)
        if not touched:
            emit("chat:cleared", {"sessionId": session_id})

    @socketio.on("chat:stop")
    def on_chat_stop(data):
        session_id = data.get("sessionId", "")
        ws_id = data.get("workspaceId") if isinstance(data, dict) else None
        if ws_id and not _ensure_workspace_membership(ws_id):
            return
        proc_key = _chat_key(ws_id, session_id) if ws_id else None
        with _chat_proc_lock:
            proc = _chat_processes.get(proc_key) if proc_key else next(
                (p for (k_ws_id, k_session_id), p in _chat_processes.items()
                 if k_session_id == session_id),
                None,
            )
        if proc and proc.poll() is None:
            try:
                _terminate_proc(proc)
            except OSError:
                pass
