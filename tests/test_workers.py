"""Tests for server/workers.py."""

import os
import signal
import subprocess
import sys
import time

import pytest
import server.workers as workers_mod

from server.init import init_workspace
from server.persistence import read_json, write_json
from server.app import reconcile
from server.tasks import create_task, read_task, update_task
from server.workers import (
    assign_task,
    check_watch_columns,
    create_auto_task,
    start_worker,
    stop_worker,
    yank_from_worker,
    _assemble_prompt,
    _auto_commit,
    _auto_pr,
    _load_layout,
    _on_agent_error,
    _on_agent_success,
    _processes,
    _refill_from_watch_column,
    _setup_worktree,
    _stop_proc_with_timeout,
    is_non_retryable_provider_error,
)
from server.agents import get_adapter, register_adapter
from tests.conftest import MockAdapter


def _wait_for_worker_threads(timeout=3.0):
    """Let daemon worker threads finish their final filesystem writes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with workers_mod._process_lock:
            if not _processes:
                return True
        time.sleep(0.02)
    return False


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


class ModelExpectingAdapter(MockAdapter):
    @property
    def name(self):
        return "claude"

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        assert model == "claude-haiku-4-5-20251001"
        return super().build_argv(prompt, model, workspace, bp_dir=bp_dir)


class GeminiCapacityExceededAdapter(MockAdapter):
    @property
    def name(self):
        return "gemini"

    def parse_output(self, stdout, stderr, exit_code):
        return {
            "success": False,
            "output": stdout.strip(),
            "error": "You have exhausted your capacity on this model.",
        }


class LiveTokenStreamAdapter(MockAdapter):
    @property
    def name(self):
        return "codex"

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        script = (
            "import json,sys,time;"
            "print(json.dumps({'type':'token_count','input_tokens':120,'cached_input_tokens':30,'output_tokens':45,'reasoning_output_tokens':10,'total_tokens':205}), flush=True);"
            "time.sleep(0.2);"
            "print('stream done', flush=True)"
        )
        return [sys.executable, "-c", script]

    def parse_output(self, stdout, stderr, exit_code):
        return {
            "success": exit_code == 0,
            "output": stdout.strip() or self._output,
            "error": None if exit_code == 0 else (stderr.strip() or f"Exit code {exit_code}"),
            "usage": {},
        }


class ThrottledTokenStreamAdapter(MockAdapter):
    """Emits two token_count events in quick succession to test throttle deferral."""
    @property
    def name(self):
        return "codex"

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        script = (
            "import json,sys,time;"
            "print(json.dumps({'type':'token_count','input_tokens':100,'output_tokens':50,'total_tokens':150}), flush=True);"
            "time.sleep(0.05);"
            "print(json.dumps({'type':'token_count','input_tokens':200,'output_tokens':100,'total_tokens':300}), flush=True);"
            "time.sleep(1);"
            "print('done', flush=True)"
        )
        return [sys.executable, "-c", script]

    def parse_output(self, stdout, stderr, exit_code):
        return {
            "success": exit_code == 0,
            "output": stdout.strip() or self._output,
            "error": None if exit_code == 0 else (stderr.strip() or f"Exit code {exit_code}"),
            "usage": {},
        }


class CapturingSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, payload, to=None):
        self.events.append((event, payload, to))


class ProcessTreeAdapter(MockAdapter):
    def __init__(self, pid_file, term_file, output="process tree"):
        super().__init__(output=output)
        self.pid_file = str(pid_file)
        self.term_file = str(term_file)

    @property
    def name(self):
        return "process-tree"

    def build_argv(self, prompt, model, workspace, bp_dir=None):
        child_code = (
            "import os,signal,sys,time\n"
            "pid_file,term_file=sys.argv[1:3]\n"
            "open(pid_file,'w').write(str(os.getpid()))\n"
            "def term(signum,frame):\n"
            "    open(term_file,'w').write('terminated')\n"
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, term)\n"
            "time.sleep(30)"
        )
        parent_code = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]]);"
            "print('parent ready', flush=True);"
            "time.sleep(30)"
        )
        return [sys.executable, "-c", parent_code, child_code, self.pid_file, self.term_file]

    def parse_output(self, stdout, stderr, exit_code):
        return {
            "success": exit_code == 0,
            "output": stdout.strip(),
            "error": stderr.strip() or f"Exit code {exit_code}",
        }


def _wait_for_path(path, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


def _cleanup_child_pid(path):
    try:
        pid = int(open(path).read().strip())
    except Exception:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    try:
        deadline = time.time() + 1.0
        while time.time() < deadline:
            os.kill(pid, 0)
            time.sleep(0.05)
    except OSError:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


@pytest.fixture
def bp_dir(tmp_workspace):
    bp = init_workspace(tmp_workspace)
    # Register mock adapter
    register_adapter("mock", MockAdapter(output="Mock agent output"))
    yield bp
    _wait_for_worker_threads()


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


class TestWorkerReconcile:
    def test_reconcile_removes_stale_idle_queue_entries(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Stale queue task")
        update_task(bp_dir, task["id"], {"status": "review", "assigned_to": ""})

        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["task_queue"] = [task["id"]]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        reconcile(bp_dir)

        updated_layout = _load_layout(bp_dir)
        assert updated_layout["slots"][worker_slot]["task_queue"] == []
        updated_task = read_task(bp_dir, task["id"])
        assert updated_task["status"] == "review"
        assert updated_task["assigned_to"] == ""

    def test_reconcile_rebuilds_queue_from_assigned_ticket(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Assigned missing queue task")
        update_task(bp_dir, task["id"], {"status": "assigned", "assigned_to": str(worker_slot)})

        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["task_queue"] = []
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        reconcile(bp_dir)

        updated_layout = _load_layout(bp_dir)
        assert updated_layout["slots"][worker_slot]["task_queue"] == [task["id"]]

    def test_reconcile_blocks_interrupted_in_progress_ticket(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Interrupted task")
        update_task(bp_dir, task["id"], {"status": "in_progress", "assigned_to": str(worker_slot)})

        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["state"] = "idle"
        layout["slots"][worker_slot]["task_queue"] = [task["id"]]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        reconcile(bp_dir)

        updated_layout = _load_layout(bp_dir)
        assert updated_layout["slots"][worker_slot]["state"] == "idle"
        assert updated_layout["slots"][worker_slot]["task_queue"] == []
        updated_task = read_task(bp_dir, task["id"])
        assert updated_task["status"] == "blocked"
        assert updated_task["assigned_to"] == ""
        assert "Bullpen restarted while this task was in progress" in updated_task["body"]

    def test_yank_uses_assigned_to_when_queue_reference_is_missing(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Assigned missing queue yank")
        update_task(bp_dir, task["id"], {"status": "in_progress", "assigned_to": str(worker_slot)})

        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["state"] = "working"
        layout["slots"][worker_slot]["task_queue"] = []
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        assert yank_from_worker(bp_dir, task["id"]) is True

        updated_layout = _load_layout(bp_dir)
        assert updated_layout["slots"][worker_slot]["state"] == "idle"
        assert updated_layout["slots"][worker_slot]["task_queue"] == []

    def test_yank_detaches_run_and_ignores_late_success(self, bp_dir, worker_slot, monkeypatch):
        task = create_task(bp_dir, "Late success yank")
        update_task(bp_dir, task["id"], {"status": "in_progress", "assigned_to": str(worker_slot)})

        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["state"] = "working"
        layout["slots"][worker_slot]["task_queue"] = [task["id"]]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        stop_calls = []

        class FakeProc:
            def poll(self):
                return None

        monkeypatch.setattr(workers_mod, "_request_process_shutdown", lambda proc: stop_calls.append(proc))
        fake_proc = FakeProc()
        _processes[(None, worker_slot)] = {
            "proc": fake_proc,
            "buffer": [],
            "buffer_size": 0,
            "task_id": task["id"],
            "run_id": "run-yank-1",
        }

        assert yank_from_worker(bp_dir, task["id"]) is True
        update_task(bp_dir, task["id"], {"status": "review", "assigned_to": ""})
        _on_agent_success(bp_dir, worker_slot, task["id"], "late output", None, run_id="run-yank-1")

        updated = read_task(bp_dir, task["id"])
        updated_layout = _load_layout(bp_dir)
        assert updated["status"] == "review"
        assert updated["assigned_to"] == ""
        assert updated_layout["slots"][worker_slot]["task_queue"] == []
        assert (None, worker_slot) not in _processes
        assert stop_calls == [fake_proc]

    def test_stop_detaches_run_and_ignores_late_error(self, bp_dir, worker_slot, monkeypatch):
        task = create_task(bp_dir, "Late error stop")
        assign_task(bp_dir, worker_slot, task["id"])
        update_task(bp_dir, task["id"], {"status": "in_progress"})

        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["state"] = "working"
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        stop_calls = []

        class FakeProc:
            def poll(self):
                return None

        monkeypatch.setattr(workers_mod, "_request_process_shutdown", lambda proc: stop_calls.append(proc))
        fake_proc = FakeProc()
        _processes[(None, worker_slot)] = {
            "proc": fake_proc,
            "buffer": [],
            "buffer_size": 0,
            "task_id": task["id"],
            "run_id": "run-stop-1",
        }

        stop_worker(bp_dir, worker_slot)
        _on_agent_error(bp_dir, worker_slot, task["id"], "late failure", None, run_id="run-stop-1")

        updated = read_task(bp_dir, task["id"])
        updated_layout = _load_layout(bp_dir)
        assert updated["status"] == "assigned"
        assert str(updated["assigned_to"]) == str(worker_slot)
        assert updated_layout["slots"][worker_slot]["state"] == "idle"
        assert updated_layout["slots"][worker_slot]["task_queue"] == [task["id"]]
        assert (None, worker_slot) not in _processes
        assert stop_calls == [fake_proc]


class TestStartWorker:
    def test_non_retryable_gemini_capacity_error_is_classified(self):
        assert is_non_retryable_provider_error("gemini", "You have exhausted your capacity on this model.")
        assert is_non_retryable_provider_error("gemini", "Error: RESOURCE HAS BEEN EXHAUSTED for this request.")
        assert not is_non_retryable_provider_error("gemini", "Temporary upstream timeout")
        assert not is_non_retryable_provider_error("claude", "You have exhausted your capacity on this model.")

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

    def test_yank_kills_auto_task_on_on_drop_worker(self, bp_dir, worker_slot):
        """Regression: yanking an auto-created task from an on_drop worker with
        an empty queue must kill the running agent. Previously the process was
        stored under (None, slot) because create_auto_task dropped ws_id, so
        yank_from_worker (called with the real ws_id) could not find it."""
        class SlowAdapter(MockAdapter):
            @property
            def name(self):
                return "slow-mock"

            def build_argv(self, prompt, model, workspace, bp_dir=None):
                return [sys.executable, "-c", "import time; time.sleep(30)"]

        register_adapter("slow-mock", SlowAdapter())
        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["agent"] = "slow-mock"
        layout["slots"][worker_slot]["activation"] = "on_drop"
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        ws_id = "test-workspace"
        start_worker(bp_dir, worker_slot, None, ws_id)
        # Give the agent subprocess time to start and register itself.
        deadline = time.time() + 3.0
        while time.time() < deadline and (ws_id, worker_slot) not in _processes:
            time.sleep(0.05)

        assert (ws_id, worker_slot) in _processes, "process not registered under real ws_id"
        assert (None, worker_slot) not in _processes, "process leaked under ws_id=None"

        from server.tasks import list_tasks
        auto = next(t for t in list_tasks(bp_dir) if t["title"].startswith("[Auto]"))
        proc = _processes[(ws_id, worker_slot)]["proc"]

        assert yank_from_worker(bp_dir, auto["id"], None, ws_id) is True

        # The subprocess should have been terminated by the yank.
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise AssertionError("yank_from_worker did not kill the agent subprocess")
        assert proc.poll() is not None

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

    def test_start_normalizes_legacy_claude_haiku_model(self, bp_dir, worker_slot):
        previous = get_adapter("claude")
        register_adapter("claude", ModelExpectingAdapter(output="normalized"))
        try:
            layout = _load_layout(bp_dir)
            layout["slots"][worker_slot]["agent"] = "claude"
            layout["slots"][worker_slot]["model"] = "claude-haiku-4-6"
            write_json(os.path.join(bp_dir, "layout.json"), layout)

            task = create_task(bp_dir, "Normalize model before run")
            assign_task(bp_dir, worker_slot, task["id"])

            start_worker(bp_dir, worker_slot)
            time.sleep(0.5)

            updated_layout = _load_layout(bp_dir)
            assert updated_layout["slots"][worker_slot]["model"] == "claude-haiku-4-5-20251001"
        finally:
            register_adapter("claude", previous)

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

    def test_non_retryable_capacity_error_blocks_without_retry(self, bp_dir, worker_slot):
        register_adapter("gemini", GeminiCapacityExceededAdapter(output="capacity fail"))
        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["agent"] = "gemini"
        layout["slots"][worker_slot]["model"] = "gemini-2.5-pro"
        layout["slots"][worker_slot]["max_retries"] = 5
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Capacity exhausted")
        assign_task(bp_dir, worker_slot, task["id"])

        start_worker(bp_dir, worker_slot)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "blocked"
        history = updated.get("history", [])
        assert sum(1 for h in history if h.get("event") == "retry") == 0
        assert "exhausted your capacity on this model" in (updated.get("body") or "").lower()

    def test_stream_usage_emits_live_task_token_updates(self, bp_dir, worker_slot):
        previous = get_adapter("codex")
        register_adapter("codex", LiveTokenStreamAdapter(output="live"))
        socket = CapturingSocket()
        try:
            layout = _load_layout(bp_dir)
            layout["slots"][worker_slot]["agent"] = "codex"
            layout["slots"][worker_slot]["model"] = "gpt-5.4"
            write_json(os.path.join(bp_dir, "layout.json"), layout)

            task = create_task(bp_dir, "Live token stream")
            assign_task(bp_dir, worker_slot, task["id"])

            start_worker(bp_dir, worker_slot, socketio=socket, ws_id="ws-live")
            time.sleep(0.7)

            task_updates = [
                payload for event, payload, _ in socket.events
                if event == "task:updated" and payload.get("id") == task["id"]
            ]
            assert any(
                update.get("status") == "in_progress" and int(update.get("tokens") or 0) >= 205
                for update in task_updates
            )
        finally:
            if previous is not None:
                register_adapter("codex", previous)

    def test_throttled_token_update_emits_via_deferred_timer(self, bp_dir, worker_slot):
        """When a token update is throttled, a deferred timer emits it later."""
        previous = get_adapter("codex")
        register_adapter("codex", ThrottledTokenStreamAdapter(output="throttled"))
        socket = CapturingSocket()
        try:
            layout = _load_layout(bp_dir)
            layout["slots"][worker_slot]["agent"] = "codex"
            layout["slots"][worker_slot]["model"] = "gpt-5.4"
            write_json(os.path.join(bp_dir, "layout.json"), layout)

            task = create_task(bp_dir, "Throttled token stream")
            assign_task(bp_dir, worker_slot, task["id"])

            start_worker(bp_dir, worker_slot, socketio=socket, ws_id="ws-throttle")
            time.sleep(2)

            task_updates = [
                payload for event, payload, _ in socket.events
                if event == "task:updated" and payload.get("id") == task["id"]
            ]
            # The second token value (300) should eventually be emitted
            # even though it arrived within the throttle window.
            token_values = [int(u.get("tokens", 0)) for u in task_updates if u.get("status") == "in_progress"]
            assert 300 in token_values, f"Expected 300 in token values, got {token_values}"
        finally:
            if previous is not None:
                register_adapter("codex", previous)


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

    def test_stop_proc_with_timeout_escalates_to_force_kill(self):
        class HungProc:
            def __init__(self):
                self.pid = os.getpid()
                self._poll = None
                self.term_calls = 0
                self.kill_calls = 0

            def poll(self):
                return self._poll

            def terminate(self):
                self.term_calls += 1

            def kill(self):
                self.kill_calls += 1
                self._poll = -9

            def wait(self, timeout=None):
                if self._poll is None:
                    raise subprocess.TimeoutExpired(cmd="hung", timeout=timeout)
                return self._poll

        proc = HungProc()
        assert _stop_proc_with_timeout(proc, graceful_timeout=0.01, force_timeout=0.01) is True
        assert proc.term_calls >= 1
        assert proc.kill_calls >= 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group behavior")
class TestWorkerProcessTree:
    def _start_process_tree_worker(self, bp_dir, worker_slot, tmp_path, *, max_retries=0):
        pid_file = tmp_path / "child.pid"
        term_file = tmp_path / "child.term"
        register_adapter("process-tree", ProcessTreeAdapter(pid_file, term_file))
        layout = _load_layout(bp_dir)
        layout["slots"][worker_slot]["agent"] = "process-tree"
        layout["slots"][worker_slot]["max_retries"] = max_retries
        write_json(os.path.join(bp_dir, "layout.json"), layout)
        task = create_task(bp_dir, "Process tree task")
        assign_task(bp_dir, worker_slot, task["id"])
        start_worker(bp_dir, worker_slot, ws_id="tree-ws")
        assert _wait_for_path(pid_file), "child process did not start"
        return task, pid_file, term_file

    def test_stop_terminates_process_tree(self, bp_dir, worker_slot, tmp_path):
        task, pid_file, term_file = self._start_process_tree_worker(bp_dir, worker_slot, tmp_path)
        try:
            stop_worker(bp_dir, worker_slot, ws_id="tree-ws")
            assert _wait_for_path(term_file), "child process did not receive SIGTERM"
            updated = read_task(bp_dir, task["id"])
            assert updated["status"] == "assigned"
        finally:
            _cleanup_child_pid(pid_file)

    def test_yank_terminates_process_tree(self, bp_dir, worker_slot, tmp_path):
        task, pid_file, term_file = self._start_process_tree_worker(bp_dir, worker_slot, tmp_path)
        try:
            assert yank_from_worker(bp_dir, task["id"], ws_id="tree-ws") is True
            assert _wait_for_path(term_file), "child process did not receive SIGTERM"
            layout = _load_layout(bp_dir)
            assert task["id"] not in layout["slots"][worker_slot]["task_queue"]
        finally:
            _cleanup_child_pid(pid_file)

    def test_timeout_terminates_process_tree_and_blocks_task(self, bp_dir, worker_slot, tmp_path):
        config = read_json(os.path.join(bp_dir, "config.json"))
        config["agent_timeout_seconds"] = 1
        write_json(os.path.join(bp_dir, "config.json"), config)

        task, pid_file, term_file = self._start_process_tree_worker(bp_dir, worker_slot, tmp_path)
        try:
            assert _wait_for_path(term_file, timeout=5.0), "child process did not receive SIGTERM"
            deadline = time.time() + 5.0
            updated = read_task(bp_dir, task["id"])
            while time.time() < deadline and updated["status"] != "blocked":
                time.sleep(0.05)
                updated = read_task(bp_dir, task["id"])
            assert updated["status"] == "blocked"
            assert "Agent timed out" in updated["body"]
        finally:
            _cleanup_child_pid(pid_file)


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
        assert "Trust Boundary" in prompt
        assert "BEGIN TASK_BODY" in prompt

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
        assert "BEGIN WORKSPACE_CONTEXT" in prompt

    def test_untrusted_mode_prompt_is_explicit(self, bp_dir, worker_slot):
        task = create_task(bp_dir, "Audit input handling", description="Ticket text may be hostile.")
        layout = _load_layout(bp_dir)
        worker = layout["slots"][worker_slot]
        worker["trust_mode"] = "untrusted"
        task_data = read_task(bp_dir, task["id"])

        prompt = _assemble_prompt(bp_dir, worker, task_data)
        assert "UNTRUSTED mode" in prompt
        assert "quoted content" in prompt

    def test_untrusted_mode_blocks_auto_commit_and_pr(self, bp_dir, worker_slot, monkeypatch):
        task = create_task(bp_dir, "Keep git side effects disabled")
        layout = _load_layout(bp_dir)
        worker = layout["slots"][worker_slot]
        worker["trust_mode"] = "untrusted"
        worker["auto_commit"] = True
        worker["auto_pr"] = True
        worker["use_worktree"] = True
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        called = {"commit": False, "pr": False}

        def fake_auto_commit(*_args, **_kwargs):
            called["commit"] = True
            return "deadbeef"

        def fake_auto_pr(*_args, **_kwargs):
            called["pr"] = True
            return "https://example.test/pr/1"

        monkeypatch.setattr(workers_mod, "_auto_commit", fake_auto_commit)
        monkeypatch.setattr(workers_mod, "_auto_pr", fake_auto_pr)

        _on_agent_success(
            bp_dir,
            worker_slot,
            task["id"],
            "done",
            socketio=None,
            agent_cwd=os.path.dirname(bp_dir),
        )

        assert called["commit"] is False
        assert called["pr"] is False


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

    def test_handoff_depth_limit_disabled_by_default(self, bp_dir):
        """Default mode does not block handoff chains at max depth."""
        max_depth = workers_mod.MAX_HANDOFF_DEPTH
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
        # Pre-set handoff_depth to max after assignment; assignment starts a fresh chain.
        assign_task(bp_dir, 0, task["id"])
        update_task(bp_dir, task["id"], {"handoff_depth": max_depth})
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "assigned"
        assert updated.get("handoff_depth", 0) == max_depth + 1

    def test_handoff_depth_exceeded(self, bp_dir, monkeypatch):
        """When enabled, task with handoff_depth at max moves to blocked."""
        monkeypatch.setattr(workers_mod, "ENFORCE_HANDOFF_CHAIN_LIMIT", True)
        max_depth = workers_mod.MAX_HANDOFF_DEPTH
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
        assign_task(bp_dir, 0, task["id"])
        update_task(bp_dir, task["id"], {"handoff_depth": max_depth})
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "blocked"
        assert "max depth" in updated["body"].lower()

    def test_handoff_depth_exceeded_task_can_run_again(self, bp_dir, monkeypatch):
        """A task that hit max handoff depth can be reassigned and run again."""
        monkeypatch.setattr(workers_mod, "ENFORCE_HANDOFF_CHAIN_LIMIT", True)
        max_depth = workers_mod.MAX_HANDOFF_DEPTH

        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [{
            "row": 0, "col": 0, "profile": "test",
            "name": "Looper", "agent": "mock", "model": "mock-model",
            "activation": "manual", "disposition": "worker:Looper",
            "watch_column": None, "expertise_prompt": "",
            "max_retries": 0, "task_queue": [], "state": "idle",
        }]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Reusable loop task")

        # First run exceeds max depth and blocks.
        assign_task(bp_dir, 0, task["id"])
        update_task(bp_dir, task["id"], {"handoff_depth": max_depth})
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        blocked = read_task(bp_dir, task["id"])
        assert blocked["status"] == "blocked"

        # Reassigning should reset depth so the task can execute again.
        assign_task(bp_dir, 0, task["id"])
        reassigned = read_task(bp_dir, task["id"])
        assert reassigned["status"] == "assigned"
        assert reassigned.get("handoff_depth", 0) == 0

        start_worker(bp_dir, 0)
        time.sleep(0.5)

        rerun = read_task(bp_dir, task["id"])
        assert rerun["status"] == "assigned"
        assert rerun.get("handoff_depth", 0) == 1

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

    def test_pass_random_direction_picks_occupied_neighbor(self, bp_dir):
        """pass:random picks from occupied neighbor directions; isolated neighbor wins."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        # Sender at (0,0); only right neighbor (0,1) is occupied.
        layout["slots"] = [
            {
                "row": 0, "col": 0, "profile": "test",
                "name": "Sender", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "pass:random",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
            {
                "row": 0, "col": 1, "profile": "test",
                "name": "Only Neighbor", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "review",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
        ]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Random direction task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated_layout = _load_layout(bp_dir)
        assert task["id"] in updated_layout["slots"][1]["task_queue"]
        assert updated_layout["slots"][0]["state"] == "idle"
        updated_task = read_task(bp_dir, task["id"])
        assert updated_task.get("handoff_depth", 0) == 1

    def test_pass_random_direction_no_neighbor_blocks(self, bp_dir):
        """pass:random with no occupied neighbor in any direction → blocked."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [{
            "row": 0, "col": 0, "profile": "test",
            "name": "Alone", "agent": "mock", "model": "mock-model",
            "activation": "manual", "disposition": "pass:random",
            "watch_column": None, "expertise_prompt": "",
            "max_retries": 0, "task_queue": [], "state": "idle",
        }]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Random direction alone task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated = read_task(bp_dir, task["id"])
        assert updated["status"] == "blocked"

    def test_random_pass_by_name(self, bp_dir):
        """random:<name> passes to a worker whose name matches."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [
            {
                "row": 0, "col": 0, "profile": "test",
                "name": "Sender", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "random:Reviewer",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
            {
                "row": 0, "col": 1, "profile": "test",
                "name": "Reviewer", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "review",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
            {
                "row": 0, "col": 2, "profile": "test",
                "name": "Other", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "review",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
        ]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Random by name task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated_layout = _load_layout(bp_dir)
        # Only "Reviewer" (slot 1) matches; "Other" must not receive it.
        assert task["id"] in updated_layout["slots"][1]["task_queue"]
        assert task["id"] not in updated_layout["slots"][2].get("task_queue", [])
        updated_task = read_task(bp_dir, task["id"])
        assert updated_task.get("handoff_depth", 0) == 1

    def test_random_pass_blank_matches_any(self, bp_dir):
        """random: (blank name) passes to any available worker except self."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [
            {
                "row": 0, "col": 0, "profile": "test",
                "name": "Sender", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "random:",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
            {
                "row": 0, "col": 1, "profile": "test",
                "name": "OnlyOther", "agent": "mock", "model": "mock-model",
                "activation": "manual", "disposition": "review",
                "watch_column": None, "expertise_prompt": "",
                "max_retries": 0, "task_queue": [], "state": "idle",
            },
        ]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Random blank task")
        assign_task(bp_dir, 0, task["id"])
        start_worker(bp_dir, 0)
        time.sleep(0.5)

        updated_layout = _load_layout(bp_dir)
        assert task["id"] in updated_layout["slots"][1]["task_queue"]

    def test_random_pass_no_match_blocks(self, bp_dir):
        """random:<name> with no matching worker → task moves to blocked."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"] = [{
            "row": 0, "col": 0, "profile": "test",
            "name": "Alone", "agent": "mock", "model": "mock-model",
            "activation": "manual", "disposition": "random:Ghost",
            "watch_column": None, "expertise_prompt": "",
            "max_retries": 0, "task_queue": [], "state": "idle",
        }]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "No match task")
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

    def test_check_watch_columns_skips_idle_watcher_with_existing_queue(self, bp_dir):
        """A watcher with queued work must not claim another task just because
        its state has not flipped to working yet."""
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        base = {
            "profile": "test", "agent": "mock", "model": "mock-model",
            "activation": "on_queue", "disposition": "review",
            "watch_column": "approved", "expertise_prompt": "",
            "max_retries": 0, "state": "idle", "paused": False,
        }
        layout["slots"] = [
            {
                **base,
                "row": 0, "col": 0, "name": "W1",
                "last_trigger_time": 50,
                "task_queue": ["already-queued-task"],
            },
            {
                **base,
                "row": 0, "col": 1, "name": "W2",
                "last_trigger_time": 100,
                "task_queue": [],
            },
        ]
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        task = create_task(bp_dir, "Approved task")
        from server.tasks import update_task
        update_task(bp_dir, task["id"], {"status": "approved"})

        check_watch_columns(bp_dir, "approved")

        updated = read_task(bp_dir, task["id"])
        layout = _load_layout(bp_dir)
        assert str(updated["assigned_to"]) == "1"
        assert task["id"] in layout["slots"][1].get("task_queue", [])
        assert task["id"] not in layout["slots"][0].get("task_queue", [])

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
        _wait_for_worker_threads()

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
