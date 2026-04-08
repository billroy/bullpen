"""Event payload validation and sanitization."""

import re
import sys

# Field constraints
MAX_TITLE = 200
MAX_DESCRIPTION = 50_000
MAX_TAG_LEN = 50
MAX_TAGS = 20
MAX_EXPERTISE_PROMPT = 100_000
MAX_SLUG = 80
MAX_PAYLOAD_SIZE = 1_000_000  # 1MB

VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
VALID_TYPES = {"task", "bug", "feature", "chore"}
VALID_AGENTS = {"claude", "codex"}
VALID_ACTIVATIONS = {"on_drop", "on_queue", "manual", "at_time", "on_interval"}
VALID_DISPOSITIONS = {"review", "done"}

ID_REGEX = re.compile(r'^[a-zA-Z0-9_-]{1,80}$')
SLUG_REGEX = re.compile(r'^[a-zA-Z0-9_-]{1,80}$')


class ValidationError(Exception):
    pass


def validate_payload_size(data):
    """Reject payloads over 1MB (rough estimate)."""
    import json
    size = len(json.dumps(data, default=str))
    if size > MAX_PAYLOAD_SIZE:
        raise ValidationError(f"Payload too large ({size} bytes, max {MAX_PAYLOAD_SIZE})")


def _str(val, max_len, field_name):
    """Validate and truncate a string field."""
    if val is None:
        return ""
    val = str(val)
    if len(val) > max_len:
        raise ValidationError(f"{field_name} exceeds max length ({len(val)} > {max_len})")
    return val


def _enum(val, allowed, field_name, default=None):
    """Validate an enum field."""
    if val is None:
        return default
    val = str(val).lower()
    if val not in allowed:
        raise ValidationError(f"Invalid {field_name}: '{val}'. Must be one of: {', '.join(sorted(allowed))}")
    return val


def _id(val, field_name="id"):
    """Validate an ID/slug field."""
    if val is None:
        return None
    val = str(val)
    if not ID_REGEX.match(val):
        raise ValidationError(f"Invalid {field_name}: must match [a-zA-Z0-9_-]{{1,80}}")
    return val


def _tags(val):
    """Validate tags list."""
    if val is None:
        return []
    if not isinstance(val, list):
        raise ValidationError("tags must be a list")
    if len(val) > MAX_TAGS:
        raise ValidationError(f"Too many tags ({len(val)} > {MAX_TAGS})")
    result = []
    for t in val:
        t = str(t)
        if len(t) > MAX_TAG_LEN:
            raise ValidationError(f"Tag too long ({len(t)} > {MAX_TAG_LEN})")
        result.append(t)
    return result


def _int(val, field_name, min_val=None, max_val=None):
    """Validate an integer field."""
    if val is None:
        return None
    try:
        val = int(val)
    except (ValueError, TypeError):
        raise ValidationError(f"{field_name} must be an integer")
    if min_val is not None and val < min_val:
        raise ValidationError(f"{field_name} must be >= {min_val}")
    if max_val is not None and val > max_val:
        raise ValidationError(f"{field_name} must be <= {max_val}")
    return val


def validate_task_create(data):
    """Validate task:create payload. Returns sanitized data."""
    validate_payload_size(data)
    return {
        "title": _str(data.get("title", "Untitled"), MAX_TITLE, "title"),
        "description": _str(data.get("description", ""), MAX_DESCRIPTION, "description"),
        "type": _enum(data.get("type"), VALID_TYPES, "type", default="task"),
        "priority": _enum(data.get("priority"), VALID_PRIORITIES, "priority", default="normal"),
        "tags": _tags(data.get("tags")),
    }


def validate_task_update(data):
    """Validate task:update payload. Returns sanitized data."""
    validate_payload_size(data)
    task_id = _id(data.get("id"), "id")
    if not task_id:
        raise ValidationError("task:update requires id")

    fields = {}
    if "title" in data:
        fields["title"] = _str(data["title"], MAX_TITLE, "title")
    if "description" in data:
        fields["description"] = _str(data["description"], MAX_DESCRIPTION, "description")
    if "type" in data:
        fields["type"] = _enum(data["type"], VALID_TYPES, "type")
    if "priority" in data:
        fields["priority"] = _enum(data["priority"], VALID_PRIORITIES, "priority")
    if "tags" in data:
        fields["tags"] = _tags(data["tags"])
    if "status" in data:
        fields["status"] = str(data["status"])
    if "order" in data:
        fields["order"] = str(data["order"])
    if "assigned_to" in data:
        fields["assigned_to"] = data["assigned_to"]

    return task_id, fields


def validate_id(data, field="id"):
    """Validate a simple {id: ...} payload."""
    val = _id(data.get(field), field)
    if not val:
        raise ValidationError(f"requires {field}")
    return val


def validate_slot(data, max_slots=100):
    """Validate a slot index."""
    slot = _int(data.get("slot"), "slot", min_val=0, max_val=max_slots - 1)
    if slot is None:
        raise ValidationError("requires slot")
    return slot


def validate_worker_configure(data, max_slots=100):
    """Validate worker:configure payload. Returns (slot, sanitized_fields)."""
    validate_payload_size(data)
    slot = validate_slot(data, max_slots)
    fields = data.get("fields", {})

    sanitized = {}
    if "name" in fields:
        sanitized["name"] = _str(fields["name"], MAX_TITLE, "name")
    if "agent" in fields:
        sanitized["agent"] = _enum(fields["agent"], VALID_AGENTS, "agent")
    if "model" in fields:
        sanitized["model"] = _str(fields["model"], 50, "model")
    if "activation" in fields:
        sanitized["activation"] = _enum(fields["activation"], VALID_ACTIVATIONS, "activation")
    if "disposition" in fields:
        sanitized["disposition"] = _enum(fields["disposition"], VALID_DISPOSITIONS, "disposition")
    if "watch_column" in fields:
        sanitized["watch_column"] = fields["watch_column"]
    if "expertise_prompt" in fields:
        sanitized["expertise_prompt"] = _str(fields["expertise_prompt"], MAX_EXPERTISE_PROMPT, "expertise_prompt")
    if "max_retries" in fields:
        sanitized["max_retries"] = _int(fields["max_retries"], "max_retries", min_val=0, max_val=10)
    if "use_worktree" in fields:
        sanitized["use_worktree"] = bool(fields["use_worktree"])
    if "auto_commit" in fields:
        sanitized["auto_commit"] = bool(fields["auto_commit"])
    if "auto_pr" in fields:
        sanitized["auto_pr"] = bool(fields["auto_pr"])
    if "trigger_time" in fields:
        val = str(fields["trigger_time"] or "")
        if val and not re.match(r'^\d{2}:\d{2}$', val):
            raise ValidationError("trigger_time must be HH:MM format")
        sanitized["trigger_time"] = val or None
    if "trigger_interval_minutes" in fields:
        sanitized["trigger_interval_minutes"] = _int(
            fields["trigger_interval_minutes"], "trigger_interval_minutes", min_val=1, max_val=1440
        )
    if "trigger_every_day" in fields:
        sanitized["trigger_every_day"] = bool(fields["trigger_every_day"])

    return slot, sanitized


def validate_grid(data):
    """Validate grid resize data. Returns (rows, cols)."""
    grid = data.get("grid")
    if not grid:
        return None, None
    rows = _int(grid.get("rows"), "rows", min_val=1, max_val=10)
    cols = _int(grid.get("cols"), "cols", min_val=1, max_val=15)
    return rows, cols
