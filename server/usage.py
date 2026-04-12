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


def _bucket_provider_model(provider, model):
    """Return normalized provider/model bucket key."""
    p = provider.strip() if isinstance(provider, str) else ""
    m = model.strip() if isinstance(model, str) else ""
    return (p or "unknown", m)


def aggregate_tokens_by_provider_model(usage_entries):
    """Aggregate usage entries into provider/model token totals."""
    if not isinstance(usage_entries, list):
        return []

    buckets = {}
    for item in usage_entries:
        if not isinstance(item, dict):
            continue

        provider, model = _bucket_provider_model(item.get("provider"), item.get("model"))
        key = (provider, model)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {"provider": provider}
            if model:
                bucket["model"] = model

        merged = merge_usage_dicts(bucket, normalize_usage(item))
        for field, value in merged.items():
            bucket[field] = value
        bucket["tokens"] = usage_to_legacy_tokens(bucket)
        buckets[key] = bucket

    ordered = []
    for provider, model in sorted(buckets.keys()):
        ordered.append(buckets[(provider, model)])
    return ordered


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


def extract_gemini_usage_event(event_obj):
    """Extract normalized usage from Gemini stream/result payloads."""
    if not isinstance(event_obj, dict):
        return {}

    usage = {}

    # JSONL result-style events.
    if event_obj.get("type") == "result":
        usage = merge_usage_dicts(usage, normalize_usage(event_obj.get("usage", {})))

    # Newer Gemini payloads include nested stats by model.
    stats = event_obj.get("stats")
    if isinstance(stats, dict):
        models = stats.get("models")
        saw_model_usage = False
        if isinstance(models, dict):
            for model_bucket in models.values():
                if not isinstance(model_bucket, dict):
                    continue
                tokens = model_bucket.get("tokens") if isinstance(model_bucket.get("tokens"), dict) else model_bucket
                model_usage = _normalize_gemini_tokens(tokens)
                if model_usage:
                    saw_model_usage = True
                    usage = merge_usage_dicts(usage, model_usage)
        # Some payload variants may provide top-level stats.tokens directly.
        if isinstance(stats.get("tokens"), dict):
            usage = merge_usage_dicts(usage, _normalize_gemini_tokens(stats.get("tokens")))
        elif not saw_model_usage:
            usage = merge_usage_dicts(usage, _normalize_gemini_tokens(stats))

    return usage


def _normalize_gemini_tokens(raw_tokens):
    """Normalize Gemini token stats object into canonical fields."""
    if not isinstance(raw_tokens, dict):
        return {}

    # Gemini often reports both "input" and "prompt"; prefer prompt when present.
    input_tokens = _coerce_non_negative_int(raw_tokens.get("prompt"))
    if input_tokens is None:
        input_tokens = _coerce_non_negative_int(raw_tokens.get("input"))
    if input_tokens is None:
        input_tokens = _coerce_non_negative_int(raw_tokens.get("input_tokens"))

    total_tokens = _coerce_non_negative_int(raw_tokens.get("total"))
    if total_tokens is None:
        total_tokens = _coerce_non_negative_int(raw_tokens.get("total_tokens"))
    cached_input_tokens = _coerce_non_negative_int(raw_tokens.get("cached"))
    reasoning_output_tokens = _coerce_non_negative_int(raw_tokens.get("thoughts"))
    candidate_tokens = _coerce_non_negative_int(raw_tokens.get("candidates"))
    tool_tokens = _coerce_non_negative_int(raw_tokens.get("tool"))

    output_tokens = _coerce_non_negative_int(raw_tokens.get("output_tokens"))
    if output_tokens is not None:
        pass
    elif total_tokens is not None and input_tokens is not None:
        output_tokens = max(total_tokens - input_tokens, 0)
    else:
        parts = [
            candidate_tokens or 0,
            reasoning_output_tokens or 0,
            tool_tokens or 0,
        ]
        summed = sum(parts)
        if summed:
            output_tokens = summed

    out = {}
    if input_tokens is not None:
        out["input_tokens"] = input_tokens
    if cached_input_tokens is not None:
        out["cached_input_tokens"] = cached_input_tokens
    if output_tokens is not None:
        out["output_tokens"] = output_tokens
    if reasoning_output_tokens is not None:
        out["reasoning_output_tokens"] = reasoning_output_tokens
    if total_tokens is not None:
        out["total_tokens"] = total_tokens
    return out


def extract_stream_usage_event(provider, event_obj):
    """Extract normalized usage from a live stream event for any provider."""
    if provider == "codex":
        return extract_codex_usage_event(event_obj)
    if provider == "gemini":
        return extract_gemini_usage_event(event_obj)

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
    tokens_by_provider_model = aggregate_tokens_by_provider_model(usage_entries)

    prev_tokens = _coerce_non_negative_int(task.get("tokens")) or 0
    return {
        "usage": usage_entries,
        "tokens_by_provider_model": tokens_by_provider_model,
        "tokens": prev_tokens + usage_to_legacy_tokens(entry),
    }
