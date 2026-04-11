"""Tests for usage accounting helpers."""

from server.usage import (
    build_usage_entry,
    build_usage_update,
    extract_codex_usage_event,
    normalize_usage,
    usage_to_legacy_tokens,
)


def test_normalize_claude_shaped_usage_with_cache_fields():
    usage = {
        "input_tokens": 300,
        "output_tokens": 120,
        "cache_read_input_tokens": 25,
        "cache_creation_input_tokens": 5,
    }

    normalized = normalize_usage(usage)
    assert normalized["input_tokens"] == 300
    assert normalized["output_tokens"] == 120
    assert normalized["cached_input_tokens"] == 30
    assert usage_to_legacy_tokens(normalized) == 420


def test_extract_codex_token_count_event():
    event = {
        "type": "token_count",
        "input_tokens": 110,
        "cached_input_tokens": 40,
        "output_tokens": 55,
        "reasoning_output_tokens": 15,
        "total_tokens": 220,
    }

    normalized = extract_codex_usage_event(event)
    assert normalized["input_tokens"] == 110
    assert normalized["cached_input_tokens"] == 40
    assert normalized["output_tokens"] == 55
    assert normalized["reasoning_output_tokens"] == 15
    assert normalized["total_tokens"] == 220
    assert usage_to_legacy_tokens(normalized) == 220


def test_build_usage_update_appends_entry_and_increments_tokens():
    task = {"tokens": 7, "usage": [{"source": "worker", "provider": "claude", "input_tokens": 10, "output_tokens": 3}]}
    entry = build_usage_entry(
        source="worker",
        provider="codex",
        model="gpt-5.4",
        slot=2,
        usage={"input_tokens": 20, "output_tokens": 5, "cached_input_tokens": 4},
        occurred_at="2026-04-11T12:00:00Z",
    )

    update = build_usage_update(task, entry)
    assert update["tokens"] == 32
    assert len(update["usage"]) == 2
    assert update["usage"][1]["source"] == "worker"
    assert update["usage"][1]["provider"] == "codex"
    assert update["usage"][1]["model"] == "gpt-5.4"
    assert update["usage"][1]["slot"] == 2
    assert update["usage"][1]["input_tokens"] == 20
    assert update["usage"][1]["output_tokens"] == 5
    assert update["usage"][1]["cached_input_tokens"] == 4
