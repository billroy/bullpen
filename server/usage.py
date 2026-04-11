"""Usage accounting helpers for ticket token metadata."""

from datetime import datetime, timezone


TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)

_TOKEN_ALIASES = {
    "input_tokens": ("input_tokens", "prompt_tokens"),
    "cached_input_tokens": (
        "cached_input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ),
    "output_tokens": ("output_tokens", "completion_tokens"),
    "reasoning_output_tokens": ("reasoning_output_tokens", "reasoning_tokens"),
    "total_tokens": ("total_tokens",),
}


def _coerce_non_negative_int(value):
    """Convert input to non-negative int or return None."""
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return n


def normalize_usage(raw_usage):
    """Normalize provider usage payloads into canonical token fields."""
    if not isinstance(raw_usage, dict):
        return {}

    normalized = {}
    for canonical, aliases in _TOKEN_ALIASES.items():
        total = 0
        seen = False
        for key in aliases:
            if key not in raw_usage:
                continue
            n = _coerce_non_negative_int(raw_usage.get(key))
            if n is None:
                continue
            total += n
            seen = True
        if seen:
            normalized[canonical] = total

    return normalized


def merge_usage_dicts(base, extra):
    """Merge two normalized usage dicts by summing known token fields."""
    out = {}
    for field in TOKEN_FIELDS:
        value = 0
        seen = False
        for src in (base, extra):
            if isinstance(src, dict) and field in src:
                n = _coerce_non_negative_int(src.get(field))
                if n is not None:
                    value += n
                    seen = True
        if seen:
            out[field] = value
    return out


def usage_to_legacy_tokens(usage):
    """Return backward-compatible token total for the legacy `tokens` scalar."""
    if not isinstance(usage, dict):
        return 0
    total = _coerce_non_negative_int(usage.get("total_tokens"))
    if total is not None:
        return total

    inp = _coerce_non_negative_int(usage.get("input_tokens")) or 0
    out = _coerce_non_negative_int(usage.get("output_tokens")) or 0
    if inp or out:
        return inp + out
    return 0


def extract_codex_usage_event(event_obj):
    """Extract normalized usage from a Codex JSON event object."""
    if not isinstance(event_obj, dict):
        return {}

    evt_type = event_obj.get("type")
    if evt_type == "turn.completed":
        return normalize_usage(event_obj.get("usage", {}))

    if evt_type == "token_count":
        usage = {}
        for candidate in (
            event_obj.get("usage"),
            event_obj.get("token_count"),
            event_obj.get("info"),
            event_obj,
        ):
            usage = merge_usage_dicts(usage, normalize_usage(candidate))
        return usage

    return {}


def extract_stream_usage_event(provider, event_obj):
    """Extract normalized usage from a live stream event for any provider."""
    if provider == "codex":
        return extract_codex_usage_event(event_obj)

    if isinstance(event_obj, dict) and event_obj.get("type") == "result":
        return normalize_usage(event_obj.get("usage", {}))

    return {}


def build_usage_entry(source, provider, model=None, slot=None, usage=None, occurred_at=None):
    """Build one structured per-run ticket usage entry."""
    normalized = normalize_usage(usage)
    if not normalized:
        return None

    entry = {
        "timestamp": occurred_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "provider": provider,
    }
    if model:
        entry["model"] = model
    if slot is not None:
        slot_int = _coerce_non_negative_int(slot)
        if slot_int is not None:
            entry["slot"] = slot_int

    entry.update(normalized)
    return entry


def build_usage_update(task, entry):
    """Create task update payload that appends usage entry and updates tokens."""
    if not isinstance(task, dict) or not isinstance(entry, dict):
        return {}

    existing_usage = task.get("usage")
    if isinstance(existing_usage, list):
        usage_entries = list(existing_usage)
    else:
        usage_entries = []
    usage_entries.append(entry)

    prev_tokens = _coerce_non_negative_int(task.get("tokens")) or 0
    return {
        "usage": usage_entries,
        "tokens": prev_tokens + usage_to_legacy_tokens(entry),
    }
