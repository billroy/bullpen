"""Tests for server/workers.py."""

import os
import subprocess
import time

import pytest

from server.init import init_workspace
from server.persistence import read_json, write_json
from server.tasks import create_task, read_task
from server.workers import (
    assign_task,
    start_worker,
    stop_worker,
    _assemble_prompt,
    _auto_commit,
    _load_layout,
    _setup_worktree,
)
from server.agents import register_adapter
from tests.conftest import MockAdapter


@pytest.fixture
def bp_dir(tmp_workspace):
    bp = init_workspace(tmp_workspace)
    # Register mock adapter
    register_adapter("mock", MockAdapter(output="Mock agent output"))
    return bp


@pytest.fixture
def worker_slot(bp_dir):
    """Create a worker in slot 0."""
    layout = read_json(os.path.join(bp_dir, "layout.json"))
    layout["slots"] = [{
        "row": 0, "col": 0,
        "profile": "test",
        "name": "Test Worker",
        "agent": "mock",
        "model": "mock-model",
        "activation": "manual",
        "disposition": "review",
        "watch_column": None,
        "expertise_prompt": "You are a test worker.",
        "max_retries": 1,
        "task_queue": [],
        "state": "idle",
    }]
    write_json(os.path.join(bp_dir, "layout.json"), layout)
    return 0


class TestAssignTask:
    def test_assign_updates_ticket(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Test task")
        assign_task(bp_dir, worker_slot, task["id"])

        updated = read_task(bp_dir, task["id"])
        assert str(updated["assigned_to"]) == "0"
        assert updated["status"] == "assigned"

    def test_assign_adds_to_queue(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Test task")
        assign_task(bp_dir, worker_slot, task["id"])

        layout = _load_layout(bp_dir)
        worker = layout["slots"][worker_slot]
        assert task["id"] in worker["task_queue"]

    def test_assign_no_duplicate(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Test task")
        assign_task(bp_dir, worker_slot, task["id"])
        assign_task(bp_dir, worker_slot, task["id"])

        layout = _load_layout(bp_dir)
        worker = layout["slots"][worker_slot]
        assert worker["task_queue"].count(task["id"]) == 1


class TestStartWorker:
    def test_start_transitions_to_working(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Test task")
        assign_task(bp_dir, worker_slot, task["id"])

        start_worker(bp_dir, worker_slot)
        # Give the thread a moment to start
        time.sleep(0.1)

        layout = _load_layout(bp_dir)
        worker = layout["slots"][worker_slot]
        # Worker should be working or already done (mock is fast)
        assert worker["state"] in ("working", "idle")

    def test_start_updates_task_status(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Test task")
        assign_task(bp_dir, worker_slot, task["id"])

        start_worker(bp_dir, worker_slot)
        time.sleep(0.5)  # Let mock agent complete

        updated = read_task(bp_dir, task["id"])
        # Task should be in disposition column (review) or still in progress
        assert updated["status"] in ("review", "in_progress")

    def test_agent_output_appended(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Test task", description="Do something")
        assign_task(bp_dir, worker_slot, task["id"])

        start_worker(bp_dir, worker_slot)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert "## Agent Output" in updated["body"]
        assert "Mock agent output" in updated["body"]

    def test_empty_queue_noop(self, bp_dir, worker_slot):
        start_worker(bp_dir, worker_slot)
        layout = _load_layout(bp_dir)
        assert layout["slots"][worker_slot]["state"] == "idle"


class TestStopWorker:
    def test_stop_returns_to_idle(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Test task")
        assign_task(bp_dir, worker_slot, task["id"])

        # Manually set state to working for test
        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["state"] = "working"
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        stop_worker(bp_dir, worker_slot)

        layout = _load_layout(bp_dir)
        assert layout["slots"][worker_slot]["state"] == "idle"

    def test_stop_task_goes_to_assigned(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Test task")
        assign_task(bp_dir, worker_slot, task["id"])

        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["state"] = "working"
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        stop_worker(bp_dir, worker_slot)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "assigned"


class TestPromptAssembly:
    def test_basic_prompt(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Build a feature", description="Details here")
        layout = _load_layout(bp_dir)
        worker = layout["slots"][worker_slot]
        task_data = read_task(bp_dir, task["id"])

        prompt = _assemble_prompt(bp_dir, worker, task_data)
        assert "Your Role" in prompt
        assert "You are a test worker" in prompt
        assert "Build a feature" in prompt
        assert "Details here" in prompt

    def test_prompt_truncation(self, bp_dir, worker_slot):
        # Set very low max chars
        config = read_json(os.path.join(bp_dir, "config.json"))
        config["max_prompt_chars"] = 100
        write_json(os.path.join(bp_dir, "config.json"), config)

        task = create_task(bp_dir, "Task", description="x" * 500)
        layout = _load_layout(bp_dir)
        worker = layout["slots"][worker_slot]
        task_data = read_task(bp_dir, task["id"])

        prompt = _assemble_prompt(bp_dir, worker, task_data)
        assert len(prompt) <= 150  # 100 + truncation message
        assert "[Prompt truncated]" in prompt

    def test_workspace_prompt_included(self, bp_dir, worker_slot):
        from server.persistence import atomic_write
        atomic_write(os.path.join(bp_dir, "workspace_prompt.md"), "This is a Flask project.")

        task = create_task(bp_dir, "Task")
        layout = _load_layout(bp_dir)
        worker = layout["slots"][worker_slot]
        task_data = read_task(bp_dir, task["id"])

        prompt = _assemble_prompt(bp_dir, worker, task_data)
        assert "This is a Flask project" in prompt


class TestWorktree:
    def test_worktree_created(self, tmp_workspace):
        """Worktree is created when use_worktree is True."""
        # Init a git repo in the workspace
        subprocess.run(["git", "init"], cwd=tmp_workspace, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_workspace, capture_output=True)

        bp_dir = os.path.join(tmp_workspace, ".bullpen")
        os.makedirs(bp_dir, exist_ok=True)

        worktree_path = _setup_worktree(tmp_workspace, bp_dir, "test-task-1")

        assert os.path.isdir(worktree_path)
        assert worktree_path == os.path.join(bp_dir, "worktrees", "test-task-1")

        # Verify the branch was created
        result = subprocess.run(
            ["git", "branch", "--list", "bullpen/test-task-1"],
            cwd=tmp_workspace, capture_output=True, text=True,
        )
        assert "bullpen/test-task-1" in result.stdout

    def test_worktree_not_git_repo(self, tmp_workspace):
        """Worktree setup fails gracefully when not a git repo."""
        bp_dir = os.path.join(tmp_workspace, ".bullpen")
        os.makedirs(bp_dir, exist_ok=True)

        with pytest.raises(RuntimeError, match="not a git repository"):
            _setup_worktree(tmp_workspace, bp_dir, "test-task-2")

    def test_worktree_path_passed_as_cwd(self, tmp_workspace):
        """Worker with use_worktree passes worktree path as agent cwd."""
        subprocess.run(["git", "init"], cwd=tmp_workspace, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_workspace, capture_output=True)

        bp_dir = init_workspace(tmp_workspace)
        register_adapter("mock", MockAdapter(output="Worktree output"))

        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [{
            "row": 0, "col": 0,
            "profile": "test",
            "name": "Worktree Worker",
            "agent": "mock",
            "model": "mock-model",
            "activation": "manual",
            "disposition": "review",
            "watch_column": None,
            "expertise_prompt": "",
            "max_retries": 0,
            "use_worktree": True,
            "task_queue": [],
            "state": "idle",
        }]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Worktree task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        # Verify worktree directory was created
        worktree_path = os.path.join(bp_dir, "worktrees", task["id"])
        assert os.path.isdir(worktree_path)


class TestAutoCommit:
    def test_auto_commit_creates_commit(self, tmp_workspace):
        """Auto-commit stages and commits changes."""
        subprocess.run(["git", "init"], cwd=tmp_workspace, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_workspace, capture_output=True)

        # Create a file to commit
        with open(os.path.join(tmp_workspace, "output.txt"), "w") as f:
            f.write("agent output")

        commit_hash = _auto_commit(tmp_workspace, "Test Task", "task-123")
        assert commit_hash is not None
        assert len(commit_hash) == 40  # full SHA

        # Verify commit message
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=tmp_workspace, capture_output=True, text=True,
        )
        assert "bullpen: Test Task [task-123]" in result.stdout

    def test_auto_commit_nothing_to_commit(self, tmp_workspace):
        """Auto-commit returns None when there are no changes."""
        subprocess.run(["git", "init"], cwd=tmp_workspace, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_workspace, capture_output=True)

        commit_hash = _auto_commit(tmp_workspace, "Test Task", "task-456")
        assert commit_hash is None

    def test_auto_commit_not_git_repo(self, tmp_workspace):
        """Auto-commit returns None gracefully when not a git repo."""
        with open(os.path.join(tmp_workspace, "output.txt"), "w") as f:
            f.write("agent output")

        commit_hash = _auto_commit(tmp_workspace, "Test Task", "task-789")
        assert commit_hash is None


class TestSharedLock:
    def test_events_and_workers_share_lock(self):
        """Events and workers modules use the same write lock instance."""
        from server.locks import write_lock
        from server import events
        from server import workers

        # events imports write_lock as _write_lock
        # workers imports write_lock as _write_lock
        # Both should be the same object
        assert workers._write_lock is write_lock
        assert events._write_lock is write_lock
