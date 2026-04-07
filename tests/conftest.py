"""Shared test fixtures."""

import os
import tempfile

import pytest


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
