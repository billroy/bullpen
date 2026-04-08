"""Tests for server/scheduler.py."""

import os
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from server.init import init_workspace
from server.persistence import read_json, write_json
from server.scheduler import Scheduler
from server.tasks import create_task
from server.workers import assign_task
from server.agents import register_adapter
from tests.conftest import MockAdapter


@pytest.fixture
def bp_dir(tmp_workspace):
    bp = init_workspace(tmp_workspace)
    register_adapter("mock", MockAdapter(output="Scheduler test output"))
    return bp


def _make_worker(bp_dir, activation="manual", **extra):
    """Create a worker in slot 0 with given activation."""
    layout = read_json(os.path.join(bp_dir, "layout.json"))
    worker = {
        "row": 0, "col": 0,
        "profile": "test",
        "name": "Scheduler Worker",
        "agent": "mock",
        "model": "mock-model",
        "activation": activation,
        "disposition": "review",
        "watch_column": None,
        "expertise_prompt": "",
        "max_retries": 0,
        "use_worktree": False,
        "auto_commit": False,
        "auto_pr": False,
        "task_queue": [],
        "state": "idle",
    }
    worker.update(extra)
    layout["slots"] = [worker]
    write_json(os.path.join(bp_dir, "layout.json"), layout)


class TestSchedulerTick:
    def test_at_time_fires(self, bp_dir):
        """Worker with at_time activation fires at matching time."""
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        _make_worker(bp_dir, activation="at_time", trigger_time=current_time, trigger_every_day=False)

        # Add a task to the queue
        task = create_task(bp_dir, "Scheduled task")
        assign_task(bp_dir, 0, task["id"])

        # Reset state to idle (assign may have auto-started)
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"][0]["state"] = "idle"
        layout["slots"][0]["activation"] = "at_time"
        layout["slots"][0]["trigger_time"] = current_time
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        scheduler = Scheduler(bp_dir, None, interval=60)
        scheduler._tick()
        time.sleep(0.5)

        # Worker should have started (state may be working or idle if fast mock)
        layout = read_json(os.path.join(bp_dir, "layout.json"))
        # Since trigger_every_day is False, activation should be reset to manual
        assert layout["slots"][0]["activation"] == "manual"

    def test_at_time_skips_wrong_time(self, bp_dir):
        """Worker with at_time doesn't fire at non-matching time."""
        _make_worker(bp_dir, activation="at_time", trigger_time="99:99", trigger_every_day=True)

        task = create_task(bp_dir, "Scheduled task")
        assign_task(bp_dir, 0, task["id"])

        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"][0]["state"] = "idle"
        layout["slots"][0]["activation"] = "at_time"
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        scheduler = Scheduler(bp_dir, None, interval=60)
        scheduler._tick()

        layout = read_json(os.path.join(bp_dir, "layout.json"))
        assert layout["slots"][0]["state"] == "idle"

    def test_skips_idle_no_tasks(self, bp_dir):
        """Worker with at_time but no queued tasks is skipped."""
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        _make_worker(bp_dir, activation="at_time", trigger_time=current_time)

        scheduler = Scheduler(bp_dir, None, interval=60)
        scheduler._tick()

        layout = read_json(os.path.join(bp_dir, "layout.json"))
        assert layout["slots"][0]["state"] == "idle"

    def test_interval_fires(self, bp_dir):
        """Worker with on_interval activation fires after elapsed time."""
        _make_worker(
            bp_dir,
            activation="on_interval",
            trigger_interval_minutes=1,
            last_trigger_time=0,  # epoch = long ago
        )

        task = create_task(bp_dir, "Interval task")
        assign_task(bp_dir, 0, task["id"])

        layout = read_json(os.path.join(bp_dir, "layout.json"))
        layout["slots"][0]["state"] = "idle"
        layout["slots"][0]["activation"] = "on_interval"
        layout["slots"][0]["last_trigger_time"] = 0
        write_json(os.path.join(bp_dir, "layout.json"), layout)

        scheduler = Scheduler(bp_dir, None, interval=60)
        scheduler._tick()
        time.sleep(0.5)

        layout = read_json(os.path.join(bp_dir, "layout.json"))
        # last_trigger_time should be updated
        assert layout["slots"][0]["last_trigger_time"] > 0
