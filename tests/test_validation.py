"""Tests for event validation and sanitization."""

import pytest
from server.validation import (
    ValidationError, validate_task_create, validate_task_update,
    validate_id, validate_slot, validate_worker_configure,
    validate_payload_size, MAX_TITLE, MAX_DESCRIPTION,
)


class TestTaskCreateValidation:
    def test_valid_create(self):
        result = validate_task_create({
            "title": "Fix bug",
            "description": "Details here",
            "type": "bug",
            "priority": "high",
            "tags": ["backend", "urgent"],
        })
        assert result["title"] == "Fix bug"
        assert result["type"] == "bug"
        assert result["priority"] == "high"
        assert result["tags"] == ["backend", "urgent"]

    def test_defaults(self):
        result = validate_task_create({})
        assert result["title"] == "Untitled"
        assert result["type"] == "task"
        assert result["priority"] == "normal"
        assert result["tags"] == []

    def test_title_too_long(self):
        with pytest.raises(ValidationError, match="title exceeds max length"):
            validate_task_create({"title": "x" * (MAX_TITLE + 1)})

    def test_description_too_long(self):
        with pytest.raises(ValidationError, match="description exceeds max length"):
            validate_task_create({"description": "x" * (MAX_DESCRIPTION + 1)})

    def test_invalid_type(self):
        with pytest.raises(ValidationError, match="Invalid type"):
            validate_task_create({"type": "invalid"})

    def test_invalid_priority(self):
        with pytest.raises(ValidationError, match="Invalid priority"):
            validate_task_create({"priority": "mega"})

    def test_too_many_tags(self):
        with pytest.raises(ValidationError, match="Too many tags"):
            validate_task_create({"tags": [f"tag{i}" for i in range(25)]})

    def test_tag_too_long(self):
        with pytest.raises(ValidationError, match="Tag too long"):
            validate_task_create({"tags": ["x" * 51]})


class TestTaskUpdateValidation:
    def test_valid_update(self):
        task_id, fields = validate_task_update({"id": "my-task-abc1", "title": "New title"})
        assert task_id == "my-task-abc1"
        assert fields["title"] == "New title"

    def test_missing_id(self):
        with pytest.raises(ValidationError, match="requires id"):
            validate_task_update({"title": "No id"})

    def test_invalid_id(self):
        with pytest.raises(ValidationError, match="Invalid id"):
            validate_task_update({"id": "../../../etc/passwd"})

    def test_strips_unknown_fields(self):
        task_id, fields = validate_task_update({"id": "abc", "title": "Ok", "unknown_field": "bad"})
        assert "unknown_field" not in fields


class TestIdValidation:
    def test_valid_id(self):
        assert validate_id({"id": "task-123_abc"}) == "task-123_abc"

    def test_path_traversal_rejected(self):
        with pytest.raises(ValidationError, match="Invalid id"):
            validate_id({"id": "../../secret"})

    def test_slash_rejected(self):
        with pytest.raises(ValidationError, match="Invalid id"):
            validate_id({"id": "task/bad"})

    def test_missing_id(self):
        with pytest.raises(ValidationError, match="requires id"):
            validate_id({})


class TestSlotValidation:
    def test_valid_slot(self):
        assert validate_slot({"slot": 5}) == 5

    def test_negative_slot(self):
        with pytest.raises(ValidationError, match="must be >= 0"):
            validate_slot({"slot": -1})

    def test_slot_too_large(self):
        with pytest.raises(ValidationError, match="must be <="):
            validate_slot({"slot": 200}, max_slots=100)

    def test_missing_slot(self):
        with pytest.raises(ValidationError, match="requires slot"):
            validate_slot({})


class TestWorkerConfigureValidation:
    def test_valid_configure(self):
        slot, fields = validate_worker_configure({
            "slot": 0,
            "fields": {
                "name": "My Worker",
                "agent": "claude",
                "activation": "on_drop",
                "disposition": "review",
                "max_retries": 3,
            }
        })
        assert slot == 0
        assert fields["name"] == "My Worker"
        assert fields["agent"] == "claude"
        assert fields["max_retries"] == 3

    def test_invalid_agent(self):
        with pytest.raises(ValidationError, match="Invalid agent"):
            validate_worker_configure({"slot": 0, "fields": {"agent": "gpt4"}})

    def test_invalid_disposition(self):
        with pytest.raises(ValidationError, match="Invalid disposition"):
            validate_worker_configure({"slot": 0, "fields": {"disposition": "yolo"}})

    def test_expertise_prompt_too_long(self):
        with pytest.raises(ValidationError, match="expertise_prompt exceeds"):
            validate_worker_configure({"slot": 0, "fields": {"expertise_prompt": "x" * 100_001}})

    def test_retries_out_of_range(self):
        with pytest.raises(ValidationError, match="must be <="):
            validate_worker_configure({"slot": 0, "fields": {"max_retries": 99}})


class TestPayloadSize:
    def test_oversized_payload_rejected(self):
        with pytest.raises(ValidationError, match="Payload too large"):
            validate_payload_size({"data": "x" * 1_100_000})
