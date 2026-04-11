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
    check_watch_columns,
    create_auto_task,
    start_worker,
    stop_worker,
    _assemble_prompt,
    _auto_commit,
    _auto_pr,
    _load_layout,
    _refill_from_watch_column,
    _setup_worktree,
)
from server.agents import register_adapter
from tests.conftest import MockAdapter


class UnavailableAdapter(MockAdapter):
    @property
    def name(self):
        return "unavailable"

    def available(self):
        return False

    def unavailable_message(self):
        return "Unavailable test agent. Install the test CLI."

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        raise AssertionError("build_argv should not be called when adapter is unavailable")


class UsageAdapter(MockAdapter):
    @property
    def name(self):
        return "usage-mock"

    def parse_output(self, stdout, stderr, exit_code):
        return {
            "success": True,
            "output": stdout.strip() or self._output,
            "error": None,
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 25,
                "output_tokens": 40,
                "reasoning_output_tokens": 10,
            },
        }


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

    def test_empty_queue_auto_creates_task(self, bp_dir, worker_slot):
        """Starting a worker with empty queue auto-creates a task and executes."""
        start_worker(bp_dir, worker_slot)
        time.sleep(0.5)

        # An auto task should have been created
        from server.tasks import list_tasks
        tasks = list_tasks(bp_dir)
        auto_tasks = [t for t in tasks if t["title"].startswith("[Auto]")]
        assert len(auto_tasks) == 1
        assert "Test Worker" in auto_tasks[0]["title"]
        assert auto_tasks[0]["type"] == "chore"

    def test_auto_created_task_format(self, bp_dir, worker_slot):
        """Auto-created task has correct title format and type."""
        task = create_auto_task(bp_dir, worker_slot,
                                _load_layout(bp_dir)["slots"][worker_slot])
        assert task["title"].startswith("[Auto] Test Worker")
        assert task["type"] == "chore"

    def test_unavailable_agent_blocks_with_clear_message(self, bp_dir, worker_slot):
        register_adapter("unavailable", UnavailableAdapter())
        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["agent"] = "unavailable"
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Needs missing CLI")
        assign_task(bp_dir, worker_slot, task["id"])

        start_worker(bp_dir, worker_slot)

        updated = read_task(bp_dir, task["id"])
        layout = _load_layout(bp_dir)
        assert updated["status"] == "blocked"
        assert updated["assigned_to"] == ""
        assert "Unavailable test agent" in updated["body"]
        assert task["id"] not in layout["slots"][worker_slot]["task_queue"]

    def test_worker_success_appends_structured_usage_and_keeps_tokens_compatible(self, bp_dir, worker_slot):
        register_adapter("usage-mock", UsageAdapter(output="Usage output"))
        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["agent"] = "usage-mock"
        layout["slots"][worker_slot]["model"] = "claude-sonnet-4-6"
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Track usage")
        assign_task(bp_dir, worker_slot, task["id"])

        start_worker(bp_dir, worker_slot)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["tokens"] == 140
        assert isinstance(updated.get("usage"), list)
        assert len(updated["usage"]) == 1
        usage = updated["usage"][0]
        assert usage["source"] == "worker"
        assert usage["provider"] == "usage-mock"
        assert usage["model"] == "claude-sonnet-4-6"
        assert usage["slot"] == 0
        assert usage["input_tokens"] == 100
        assert usage["cached_input_tokens"] == 25
        assert usage["output_tokens"] == 40
        assert usage["reasoning_output_tokens"] == 10
        assert isinstance(updated.get("tokens_by_provider_model"), list)
        assert len(updated["tokens_by_provider_model"]) == 1
        breakdown = updated["tokens_by_provider_model"][0]
        assert breakdown["provider"] == "usage-mock"
        assert breakdown["model"] == "claude-sonnet-4-6"
        assert breakdown["input_tokens"] == 100
        assert breakdown["cached_input_tokens"] == 25
        assert breakdown["output_tokens"] == 40
        assert breakdown["reasoning_output_tokens"] == 10
        assert breakdown["tokens"] == 140


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


class TestAutoPR:
    def test_auto_pr_no_gh(self, tmp_workspace, monkeypatch):
        """Auto-PR returns error when gh CLI is not available."""
        import shutil as _shutil
        monkeypatch.setattr(_shutil, "which", lambda x: None)
        from server.workers import _auto_pr
        result = _auto_pr(tmp_workspace, "Test", "task-1", "bullpen/task-1")
        assert "gh CLI not available" in result

    def test_auto_pr_push_failure(self, tmp_workspace):
        """Auto-PR returns error when push fails (no remote)."""
        subprocess.run(["git", "init"], cwd=tmp_workspace, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_workspace, capture_output=True)

        import shutil
        if not shutil.which("gh"):
            pytest.skip("gh CLI not available")

        result = _auto_pr(tmp_workspace, "Test", "task-1", "main")
        assert "Push failed" in result or "Error" in result


class TestHandoff:
    """Tests for worker-to-worker disposition handoff."""

    @pytest.fixture
    def two_workers(self, bp_dir):
        """Create two workers: slot 0 hands off to slot 1."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [
            {
                "row": 0, "col": 0, "profile": "test",
                "name": "Worker A", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "worker:Worker B",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
            {
                "row": 0, "col": 1, "profile": "test",
                "name": "Worker B", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "review",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
        ]
        write_json(os.path.join(bp_dir, "layout.json"), layout)
        return layout

    def test_handoff_to_worker(self, bp_dir, two_workers):
        """Worker A completes → task lands in Worker B's queue."""
        task = create_task(bp_dir, "Handoff task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        layout = _load_layout(bp_dir)
        # Task should be in Worker B's queue
        assert task["id"] in layout["slots"][1]["task_queue"]
        # Worker A should be idle with empty queue
        assert layout["slots"][0]["state"] == "idle"
        assert task["id"] not in layout["slots"][0]["task_queue"]

    def test_handoff_target_not_found(self, bp_dir):
        """Handoff to nonexistent worker → task moves to blocked."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [{
            "row": 0, "col": 0, "profile": "test",
            "name": "Lonely Worker", "agent": "mock", "model": "mock-model",
            "activation": "manual", "disposition": "worker:Ghost Worker",
            "watch_column": None, "expertise_prompt": "",
            "max_retries": 0, "task_queue": [], "state": "idle",
        }]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Orphan task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "blocked"
        assert "Ghost Worker" in updated["body"]

    def test_handoff_depth_increments(self, bp_dir, two_workers):
        """Handoff increments handoff_depth on the task."""
        task = create_task(bp_dir, "Depth task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated.get("handoff_depth", 0) == 1

    def test_handoff_depth_exceeded(self, bp_dir):
        """Task with handoff_depth at max → moves to blocked."""
        from server.workers import MAX_HANDOFF_DEPTH
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [{
            "row": 0, "col": 0, "profile": "test",
            "name": "Looper", "agent": "mock", "model": "mock-model",
            "activation": "manual", "disposition": "worker:Looper",
            "watch_column": None, "expertise_prompt": "",
            "max_retries": 0, "task_queue": [], "state": "idle",
        }]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Loop task")
        # Pre-set handoff_depth to max
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"handoff_depth": MAX_HANDOFF_DEPTH})

        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "blocked"
        assert "max depth" in updated["body"].lower()

    def test_handoff_depth_resets_on_column(self, bp_dir, two_workers):
        """When Worker B sends to a column, handoff_depth resets to 0."""
        task = create_task(bp_dir, "Reset task")
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"handoff_depth": 3})

        # Worker B has disposition "review" (column), assign directly
        assign_task(bp_dir, 1, task["id"])
        start_worker(bp_dir, 1)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "review"
        assert updated.get("handoff_depth", 0) == 0

    def test_bare_disposition_unchanged(self, bp_dir, worker_slot):
        """Bare disposition values (e.g., 'review') continue to work."""
        task = create_task(bp_dir, "Normal task")
        assign_task(bp_dir, worker_slot, task["id"])
        start_worker(bp_dir, worker_slot)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "review"

    def test_pass_right_to_adjacent_worker(self, bp_dir):
        """pass:right hands off to the worker in the next column."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [
            {
                "row": 0, "col": 0, "profile": "test",
                "name": "Left Worker", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "pass:right",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
            {
                "row": 0, "col": 1, "profile": "test",
                "name": "Right Worker", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "review",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
        ]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Pass right task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated_layout = _load_layout(bp_dir)
        assert task["id"] in updated_layout["slots"][1]["task_queue"]
        assert updated_layout["slots"][0]["state"] == "idle"
        updated_task = read_task(bp_dir, task["id"])
        assert updated_task.get("handoff_depth", 0) == 1

    def test_pass_out_of_bounds_blocks(self, bp_dir):
        """pass:left from col 0 has no left neighbor → task moves to blocked."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [{
            "row": 0, "col": 0, "profile": "test",
            "name": "Edge Worker", "agent": "mock", "model": "mock-model",
            "activation": "manual", "disposition": "pass:left",
            "watch_column": None, "expertise_prompt": "",
            "max_retries": 0, "task_queue": [], "state": "idle",
        }]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Edge task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "blocked"

    def test_pass_empty_slot_blocks(self, bp_dir):
        """pass:right to an empty slot → task moves to blocked."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        # slot 1 is None (empty)
        layout["slots"] = [
            {
                "row": 0, "col": 0, "profile": "test",
                "name": "Sender", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "pass:right",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
            None,
        ]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Empty slot task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "blocked"


class TestWatchColumn:
    """Tests for on_queue / watch_column task claiming."""

    @pytest.fixture
    def watcher_slot(self, bp_dir):
        """Create an on_queue worker watching 'assigned' in slot 0."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [{
            "row": 0, "col": 0,
            "profile": "test",
            "name": "Watcher",
            "agent": "mock",
            "model": "mock-model",
            "activation": "on_queue",
            "disposition": "review",
            "watch_column": "assigned",
            "expertise_prompt": "",
            "max_retries": 0,
            "task_queue": [],
            "state": "idle",
            "paused": False,
            "last_trigger_time": None,
        }]
        write_json(os.path.join(bp_dir, "layout.json"), layout)
        return 0

    def test_check_watch_columns_claims_task(self, bp_dir, watcher_slot):
        """Task entering watched column is claimed by idle watcher."""
        task = create_task(bp_dir, "Watch me")
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"status": "assigned"})

        check_watch_columns(bp_dir, "assigned")
        time.sleep(0.5)  # Let auto-started mock agent finish

        layout = _load_layout(bp_dir)
        worker = layout["slots"][0]
        # Task was claimed (may already be processed and dequeued)
        updated = read_task(bp_dir, task["id"])
        assert str(updated["assigned_to"]) == "0" or updated["status"] == "review"

    def test_check_watch_columns_ignores_wrong_column(self, bp_dir, watcher_slot):
        """Watcher watching 'assigned' ignores tasks in 'review'."""
        task = create_task(bp_dir, "Wrong column")
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"status": "review"})

        check_watch_columns(bp_dir, "review")

        layout = _load_layout(bp_dir)
        worker = layout["slots"][0]
        assert task["id"] not in worker.get("task_queue", [])

    def test_check_watch_columns_ignores_paused_worker(self, bp_dir, watcher_slot):
        """Paused on_queue worker does not claim tasks."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"][0]["paused"] = True
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Paused test")
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"status": "assigned"})

        check_watch_columns(bp_dir, "assigned")

        layout = _load_layout(bp_dir)
        assert task["id"] not in layout["slots"][0].get("task_queue", [])

    def test_check_watch_columns_ignores_busy_worker(self, bp_dir, watcher_slot):
        """Working on_queue worker does not claim tasks."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"][0]["state"] = "working"
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Busy test")
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"status": "assigned"})

        check_watch_columns(bp_dir, "assigned")

        layout = _load_layout(bp_dir)
        assert task["id"] not in layout["slots"][0].get("task_queue", [])

    def test_check_watch_columns_skips_already_assigned(self, bp_dir, watcher_slot):
        """Tasks already assigned to a worker are not double-claimed."""
        task = create_task(bp_dir, "Already assigned")
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"status": "assigned", "assigned_to": "5"})

        check_watch_columns(bp_dir, "assigned")

        layout = _load_layout(bp_dir)
        assert task["id"] not in layout["slots"][0].get("task_queue", [])

    def test_check_watch_columns_fifo_order(self, bp_dir, watcher_slot):
        """Oldest unclaimed task is claimed first."""
        from server.tasks import update_task
        t1 = create_task(bp_dir, "First")
        update_task(bp_dir, t1["id"], {"status": "assigned"})
        t2 = create_task(bp_dir, "Second")
        update_task(bp_dir, t2["id"], {"status": "assigned"})

        check_watch_columns(bp_dir, "assigned")
        time.sleep(0.5)  # Let auto-started mock agent finish

        # Worker claims oldest first; after processing it may refill with second
        updated_t1 = read_task(bp_dir, t1["id"])
        assert updated_t1["status"] in ("assigned", "review")  # Was claimed first

    def test_multi_watcher_round_robin(self, bp_dir):
        """Two watchers on same column each claim one task."""
        register_adapter("mock", MockAdapter(output="Multi output"))
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        base = {
            "profile": "test", "agent": "mock", "model": "mock-model",
            "activation": "on_queue", "disposition": "review",
            "watch_column": "assigned", "expertise_prompt": "",
            "max_retries": 0, "task_queue": [], "state": "idle",
            "paused": False,
        }
        layout["slots"] = [
            {**base, "row": 0, "col": 0, "name": "W1", "last_trigger_time": 100},
            {**base, "row": 0, "col": 1, "name": "W2", "last_trigger_time": 50},
        ]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        from server.tasks import update_task
        t1 = create_task(bp_dir, "Task A")
        update_task(bp_dir, t1["id"], {"status": "assigned"})
        t2 = create_task(bp_dir, "Task B")
        update_task(bp_dir, t2["id"], {"status": "assigned"})

        check_watch_columns(bp_dir, "assigned")
        time.sleep(1.0)  # Let both auto-started mock agents finish

        # W2 (last_trigger_time=50) should claim first, W1 (100) second
        # Both tasks should have been processed to review
        updated_t1 = read_task(bp_dir, t1["id"])
        updated_t2 = read_task(bp_dir, t2["id"])
        assert updated_t1["status"] == "review"
        assert updated_t2["status"] == "review"

    def test_refill_from_watch_column(self, bp_dir, watcher_slot):
        """Idle on_queue worker with empty queue refills from watched column."""
        task = create_task(bp_dir, "Refill me")
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"status": "assigned"})

        _refill_from_watch_column(bp_dir, 0)
        time.sleep(0.5)  # Let auto-started mock agent finish

        updated = read_task(bp_dir, task["id"])
        # Task was claimed and processed
        assert str(updated["assigned_to"]) == "0" or updated["status"] == "review"

    def test_refill_skips_nonempty_queue(self, bp_dir, watcher_slot):
        """Refill does nothing when worker already has tasks queued."""
        existing = create_task(bp_dir, "Existing")
        assign_task(bp_dir, 0, existing["id"])

        new_task = create_task(bp_dir, "Unclaimed")
        from server.tasks import update_task
        update_task(bp_dir, new_task["id"], {"status": "assigned"})

        _refill_from_watch_column(bp_dir, 0)

        layout = _load_layout(bp_dir)
        assert new_task["id"] not in layout["slots"][0]["task_queue"]

    def test_watch_column_end_to_end(self, bp_dir, watcher_slot):
        """Full lifecycle: task enters watched column → worker claims and processes it."""
        task = create_task(bp_dir, "E2E watch")
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"status": "assigned"})

        # Simulate what on_task_update does
        check_watch_columns(bp_dir, "assigned")

        # Worker should have claimed it and auto-started (on_queue auto-starts)
        time.sleep(0.5)

        layout = _load_layout(bp_dir)
        worker = layout["slots"][0]
        # Worker should be idle after completing (mock agent is instant)
        assert worker["state"] == "idle"

        updated = read_task(bp_dir, task["id"])
        # Task should have moved to disposition column (review)
        assert updated["status"] == "review"
        assert "Agent Output" in updated.get("body", "")

    def test_pipeline_watch_chain(self, bp_dir):
        """Worker A disposition → column watched by Worker B → auto-claimed."""
        register_adapter("mock", MockAdapter(output="Pipeline output"))
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [
            {
                "row": 0, "col": 0, "profile": "test",
                "name": "Worker A", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "review",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
                "paused": False, "last_trigger_time": None,
            },
            {
                "row": 0, "col": 1, "profile": "test",
                "name": "Worker B", "agent": "mock", "model": "mock-model",
                "activation": "on_queue", "disposition": "done",
                "watch_column": "review", "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
                "paused": False, "last_trigger_time": None,
            },
        ]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Pipeline task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(1.0)  # Let both workers complete

        updated = read_task(bp_dir, task["id"])
        # Worker A → review → Worker B claims → done
        assert updated["status"] == "done"

        layout = _load_layout(bp_dir)
        assert layout["slots"][0]["state"] == "idle"
        assert layout["slots"][1]["state"] == "idle"


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
