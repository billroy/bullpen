"""Tests for usage accounting helpers."""

from server.usage import (
    build_usage_entry,
    build_usage_update,
    extract_codex_usage_event,
    extract_gemini_usage_event,
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


def test_extract_codex_token_count_event_prefers_nested_totals_without_double_count():
    event = {
        "type": "token_count",
        "info": {
            "total_token_usage": {
                "input_tokens": 120,
                "cached_input_tokens": 30,
                "output_tokens": 45,
                "reasoning_output_tokens": 10,
                "total_tokens": 205,
            },
            # Smaller per-step snapshot should not be added to totals.
            "last_token_usage": {
                "input_tokens": 0,
                "output_tokens": 2,
                "total_tokens": 2,
            },
        },
    }

    normalized = extract_codex_usage_event(event)
    assert normalized["input_tokens"] == 120
    assert normalized["cached_input_tokens"] == 30
    assert normalized["output_tokens"] == 45
    assert normalized["reasoning_output_tokens"] == 10
    assert normalized["total_tokens"] == 205
    assert usage_to_legacy_tokens(normalized) == 205


def test_extract_gemini_stats_models_usage_event():
    event = {
        "session_id": "s1",
        "response": "Aloha. How can I help you today?",
        "stats": {
            "models": {
                "gemini-2.5-flash": {
                    "tokens": {
                        "input": 9058,
                        "prompt": 9058,
                        "candidates": 10,
                        "total": 9111,
                        "cached": 0,
                        "thoughts": 43,
                        "tool": 0,
                    }
                }
            }
        },
    }

    normalized = extract_gemini_usage_event(event)
    assert normalized["input_tokens"] == 9058
    assert normalized["output_tokens"] == 53
    assert normalized["reasoning_output_tokens"] == 43
    assert normalized["total_tokens"] == 9111
    assert normalized["cached_input_tokens"] == 0
    assert usage_to_legacy_tokens(normalized) == 9111


def test_extract_gemini_stream_result_usage_event():
    event = {
        "type": "result",
        "status": "success",
        "stats": {
            "total_tokens": 6812,
            "input_tokens": 6791,
            "output_tokens": 2,
            "cached": 0,
            "models": {
                "gemini-2.5-flash": {
                    "total_tokens": 6812,
                    "input_tokens": 6791,
                    "output_tokens": 2,
                    "cached": 0,
                }
            },
        },
    }

    normalized = extract_gemini_usage_event(event)
    assert normalized["input_tokens"] == 6791
    assert normalized["output_tokens"] == 2
    assert normalized["total_tokens"] == 6812
    assert normalized["cached_input_tokens"] == 0


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
    assert len(update["tokens_by_provider_model"]) == 2
    claude = update["tokens_by_provider_model"][0]
    codex = update["tokens_by_provider_model"][1]
    assert claude["provider"] == "claude"
    assert claude["tokens"] == 13
    assert codex["provider"] == "codex"
    assert codex["model"] == "gpt-5.4"
    assert codex["input_tokens"] == 20
    assert codex["output_tokens"] == 5
    assert codex["cached_input_tokens"] == 4
    assert codex["tokens"] == 25


def test_build_usage_update_separates_provider_and_model_totals():
    task = {
        "tokens": 0,
        "usage": [
            {"source": "worker", "provider": "codex", "model": "gpt-5.4", "input_tokens": 40, "output_tokens": 10},
            {"source": "worker", "provider": "codex", "model": "gpt-5.4-mini", "input_tokens": 20, "output_tokens": 5},
            {"source": "chat", "provider": "claude", "model": "claude-sonnet-4-6", "total_tokens": 70},
        ],
    }
    entry = build_usage_entry(
        source="worker",
        provider="codex",
        model="gpt-5.4",
        usage={"input_tokens": 15, "output_tokens": 5},
    )
    update = build_usage_update(task, entry)

    assert len(update["tokens_by_provider_model"]) == 3
    assert update["tokens_by_provider_model"][0]["provider"] == "claude"
    assert update["tokens_by_provider_model"][0]["model"] == "claude-sonnet-4-6"
    assert update["tokens_by_provider_model"][0]["total_tokens"] == 70
    assert update["tokens_by_provider_model"][0]["tokens"] == 70
    assert update["tokens_by_provider_model"][1]["provider"] == "codex"
    assert update["tokens_by_provider_model"][1]["model"] == "gpt-5.4"
    assert update["tokens_by_provider_model"][1]["input_tokens"] == 55
    assert update["tokens_by_provider_model"][1]["output_tokens"] == 15
    assert update["tokens_by_provider_model"][1]["tokens"] == 70
    assert update["tokens_by_provider_model"][2]["provider"] == "codex"
    assert update["tokens_by_provider_model"][2]["model"] == "gpt-5.4-mini"
    assert update["tokens_by_provider_model"][2]["input_tokens"] == 20
    assert update["tokens_by_provider_model"][2]["output_tokens"] == 5
    assert update["tokens_by_provider_model"][2]["tokens"] == 25
