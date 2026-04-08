"""Tests for server/tasks.py."""

import os

import pytest

from server.init import init_workspace
from server.tasks import (
    create_task,
    read_task,
    update_task,
    delete_task,
    archive_task,
    archive_done_tasks,
    clear_task_output,
    list_tasks,
    generate_slug,
    slugify,
    generate_order_key,
    midpoint_key,
)


@pytest.fixture
def bp_dir(tmp_workspace):
    """Initialize a workspace and return .bullpen/ path."""
    return init_workspace(tmp_workspace)


class TestSlugGeneration:
    def test_slugify_basic(self):
        assert slugify("Add Auth Middleware") == "add-auth-middleware"

    def test_slugify_special_chars(self):
        assert slugify("Fix: handle 'quotes'") == "fix-handle-quotes"

    def test_slugify_long_title(self):
        title = "a" * 100
        assert len(slugify(title)) <= 60

    def test_generate_slug_has_suffix(self):
        slug = generate_slug("Test Task")
        assert slug.startswith("test-task-")
        assert len(slug.split("-")[-1]) == 4

    def test_generate_slug_unique(self):
        slugs = {generate_slug("Same Title") for _ in range(20)}
        assert len(slugs) == 20  # all unique


class TestOrderKeys:
    def test_initial_key(self):
        key = generate_order_key()
        assert key == "V"

    def test_midpoint_basic(self):
        mid = midpoint_key("A", "Z")
        assert "A" < mid < "Z"

    def test_midpoint_close(self):
        mid = midpoint_key("A", "B")
        assert "A" < mid < "B"

    def test_midpoint_generates_sequence(self):
        """Insert several keys in sequence, verify they sort correctly."""
        keys = ["V"]
        # Insert before first
        keys.insert(0, midpoint_key("", keys[0]))
        # Insert after last
        keys.append(midpoint_key(keys[-1], ""))
        # Insert between first two
        keys.insert(1, midpoint_key(keys[0], keys[2]))

        assert keys == sorted(keys)

    def test_midpoint_many_insertions(self):
        """Many insertions at the same position should not fail."""
        key = "V"
        keys = [key]
        for _ in range(20):
            new_key = midpoint_key("", keys[0])
            assert new_key < keys[0]
            keys.insert(0, new_key)
        assert keys == sorted(keys)


class TestTaskCRUD:
    def test_create_and_read(self, bp_dir):
        task = create_task(bp_dir, "Test Task", description="A test")
        assert task["title"] == "Test Task"
        assert task["status"] == "inbox"
        assert task["type"] == "task"
        assert task["priority"] == "normal"
        assert task["tags"] == []
        assert "## Description" in task["body"]

        read_back = read_task(bp_dir, task["id"])
        assert read_back["title"] == "Test Task"
        assert read_back["status"] == "inbox"

    def test_create_with_tags(self, bp_dir):
        task = create_task(bp_dir, "Tagged", tags=["backend", "auth"])
        assert task["tags"] == ["backend", "auth"]
        read_back = read_task(bp_dir, task["id"])
        assert read_back["tags"] == ["backend", "auth"]

    def test_update(self, bp_dir):
        task = create_task(bp_dir, "Update Me")
        updated = update_task(bp_dir, task["id"], {"status": "assigned", "priority": "high"})
        assert updated["status"] == "assigned"
        assert updated["priority"] == "high"
        assert updated["title"] == "Update Me"

    def test_update_body(self, bp_dir):
        task = create_task(bp_dir, "Body Update")
        updated = update_task(bp_dir, task["id"], {"body": "\nNew body content.\n"})
        assert updated["body"] == "\nNew body content.\n"

    def test_delete(self, bp_dir):
        task = create_task(bp_dir, "Delete Me")
        assert read_task(bp_dir, task["id"]) is not None
        delete_task(bp_dir, task["id"])
        assert read_task(bp_dir, task["id"]) is None

    def test_list_tasks(self, bp_dir):
        create_task(bp_dir, "Task A")
        create_task(bp_dir, "Task B")
        create_task(bp_dir, "Task C")
        tasks = list_tasks(bp_dir)
        assert len(tasks) == 3

    def test_list_tasks_sorted_by_order(self, bp_dir):
        t1 = create_task(bp_dir, "First")
        update_task(bp_dir, t1["id"], {"order": "A"})
        t2 = create_task(bp_dir, "Second")
        update_task(bp_dir, t2["id"], {"order": "M"})
        t3 = create_task(bp_dir, "Third")
        update_task(bp_dir, t3["id"], {"order": "Z"})

        tasks = list_tasks(bp_dir)
        titles = [t["title"] for t in tasks]
        assert titles == ["First", "Second", "Third"]

    def test_read_nonexistent(self, bp_dir):
        assert read_task(bp_dir, "nonexistent-1234") is None

    def test_clear_output(self, bp_dir):
        task = create_task(bp_dir, "With Output", description="Keep this")
        body_with_output = task["body"] + "\n## Agent Output\n\nSome agent output here.\n"
        update_task(bp_dir, task["id"], {"body": body_with_output})

        cleared = clear_task_output(bp_dir, task["id"])
        assert "## Agent Output" not in cleared["body"]
        assert "## Description" in cleared["body"]
        assert "Keep this" in cleared["body"]

    def test_clear_output_no_output_section(self, bp_dir):
        task = create_task(bp_dir, "No Output", description="Just a task")
        cleared = clear_task_output(bp_dir, task["id"])
        assert "## Description" in cleared["body"]

    def test_frontmatter_round_trip(self, bp_dir):
        """Verify beans-compatible fields survive round-trip."""
        task = create_task(bp_dir, "Round Trip", task_type="bug", priority="urgent", tags=["fix"])
        read_back = read_task(bp_dir, task["id"])
        assert read_back["type"] == "bug"
        assert read_back["priority"] == "urgent"
        assert read_back["tags"] == ["fix"]
        assert read_back["assigned_to"] == ""
        assert "created_at" in read_back
        assert "updated_at" in read_back


class TestArchive:
    def test_archive_task(self, bp_dir):
        task = create_task(bp_dir, "Archive Me")
        task_id = task["id"]
        archive_task(bp_dir, task_id)
        # No longer in active tasks
        assert read_task(bp_dir, task_id) is None
        assert task_id not in [t["id"] for t in list_tasks(bp_dir)]
        # File exists in archive
        archive_path = os.path.join(bp_dir, "tasks", "archive", f"{task_id}.md")
        assert os.path.exists(archive_path)

    def test_archive_nonexistent_task(self, bp_dir):
        # Should not raise
        archive_task(bp_dir, "nonexistent-1234")

    def test_archive_done_tasks(self, bp_dir):
        t1 = create_task(bp_dir, "Done Task")
        update_task(bp_dir, t1["id"], {"status": "done"})
        t2 = create_task(bp_dir, "Also Done")
        update_task(bp_dir, t2["id"], {"status": "done"})
        t3 = create_task(bp_dir, "Still Active")
        update_task(bp_dir, t3["id"], {"status": "in_progress"})

        archived = archive_done_tasks(bp_dir)
        assert set(archived) == {t1["id"], t2["id"]}
        # Active task remains
        remaining = list_tasks(bp_dir)
        assert len(remaining) == 1
        assert remaining[0]["id"] == t3["id"]

    def test_list_excludes_archived(self, bp_dir):
        t1 = create_task(bp_dir, "Keep")
        t2 = create_task(bp_dir, "Archive")
        archive_task(bp_dir, t2["id"])
        tasks = list_tasks(bp_dir)
        assert len(tasks) == 1
        assert tasks[0]["id"] == t1["id"]
