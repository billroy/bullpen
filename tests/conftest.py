"""Shared test fixtures."""

import os
import tempfile
import time

import pytest

from server.agents.base import AgentAdapter


@pytest.fixture
def tmp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory(prefix="bullpen_test_") as d:
        yield d


@pytest.fixture
def tmp_file(tmp_workspace):
    """Return a helper to create a file in the temp workspace."""
    def _make(name, content=""):
        path = os.path.join(tmp_workspace, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path
    return _make


class MockAdapter(AgentAdapter):
    """Mock agent adapter for testing."""

    def __init__(self, output="Mock output", exit_code=0, delay=0):
        self._output = output
        self._exit_code = exit_code
        self._delay = delay

    @property
    def name(self):
        return "mock"

    def available(self):
        return True

    def list_models(self):
        return ["mock-model"]

    def build_argv(self, prompt, model, workspace):
        # Use echo to simulate output; actual execution handled by worker
        return ["echo", self._output]

    def parse_output(self, stdout, stderr, exit_code):
        if exit_code == 0:
            return {"success": True, "output": stdout.strip(), "error": None}
        return {"success": False, "output": stdout.strip(), "error": stderr.strip() or f"Exit code {exit_code}"}


@pytest.fixture
def mock_adapter():
    """Return a MockAdapter instance."""
    return MockAdapter()
