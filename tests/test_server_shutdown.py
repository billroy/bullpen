"""Real-process regression coverage for Bullpen server shutdown."""

from __future__ import annotations

import errno
import json
import os
import pty
import select
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(os.environ.get("BULLPEN_SHUTDOWN_TEST_SOURCE_ROOT", ROOT)).resolve()
HELPER = ROOT / "tests" / "helpers" / "shutdown_server.py"
MODEL_CLIENT = ROOT / "tests" / "helpers" / "shutdown_model_client.py"
CATALOG_STAGE_MARKERS = {
    "cert-path-blocked": b"CATALOG_STAGE cert-path",
    "ssl-context-blocked": b"CATALOG_STAGE ssl-context",
    "urlopen-blocked": b"CATALOG_STAGE urlopen",
}


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _read_available(fd):
    chunks = []
    while True:
        readable, _, _ = select.select([fd], [], [], 0)
        if not readable:
            break
        try:
            chunk = os.read(fd, 65536)
        except OSError as error:
            if error.errno == errno.EIO:
                break
            raise
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _wait_for_output(fd, expected, timeout=10):
    output = bytearray()
    deadline = time.monotonic() + timeout
    while expected not in output and time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.1)
        if readable:
            output.extend(_read_available(fd))
    if expected not in output:
        raise AssertionError(f"server did not become ready; output={output.decode(errors='replace')}")
    return output


def _wait_for_exit(pid, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return status
        time.sleep(0.02)
    return None


def _run_shutdown_case(
    tmp_path,
    *,
    catalog_mode,
    refresh_browser,
    swallow_sigint=False,
    skip_sigint_restore=False,
    exercise_models=False,
    block_on_model_request=False,
    audit_signals=False,
    workspace_count=1,
):
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    if workspace_count > 1:
        global_dir = home / ".bullpen"
        global_dir.mkdir()
        projects = []
        for index in range(workspace_count - 1):
            project = tmp_path / f"registered-workspace-{index}"
            project.mkdir()
            projects.append({
                "id": f"synthetic-{index}",
                "path": str(project),
                "name": f"Synthetic {index}",
            })
        (global_dir / "projects.json").write_text(json.dumps({
            "version": 1,
            "projects": projects,
        }))
    port = _free_port()
    env = os.environ.copy()
    env.update({
        "HOME": str(home),
        "PYTHONPATH": str(SOURCE_ROOT),
        "BULLPEN_SHUTDOWN_TEST_CATALOG": catalog_mode,
        "BULLPEN_SHUTDOWN_TEST_SWALLOW_SIGINT": "1" if swallow_sigint else "0",
        "BULLPEN_SHUTDOWN_TEST_SKIP_SIGINT_RESTORE": "1" if skip_sigint_restore else "0",
        "BULLPEN_SHUTDOWN_TEST_AUDIT_SIGNALS": "1" if audit_signals else "0",
    })

    pid, master_fd = pty.fork()
    if pid == 0:
        os.chdir(SOURCE_ROOT)
        os.execve(sys.executable, [
            sys.executable,
            str(HELPER),
            "--workspace",
            str(workspace),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-browser",
        ], env)

    output = bytearray()
    child_reaped = False
    model_client = None
    try:
        output.extend(_wait_for_output(master_fd, b"Press CTRL+C to quit"))
        stage_marker = CATALOG_STAGE_MARKERS.get(catalog_mode)
        if stage_marker and stage_marker not in output:
            output.extend(_wait_for_output(master_fd, stage_marker))
        if refresh_browser:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                assert response.status == 200
        if exercise_models:
            subprocess.run(
                [sys.executable, str(MODEL_CLIENT), str(port)],
                cwd=ROOT,
                env=env,
                timeout=60,
                check=True,
            )
        if block_on_model_request:
            model_client = subprocess.Popen(
                [sys.executable, str(MODEL_CLIENT), str(port), "claude-only"],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            readable, _, _ = select.select([model_client.stdout], [], [], 10)
            assert readable, "model client did not issue the Claude request"
            assert model_client.stdout.readline().strip() == "MODEL_REQUEST_SENT claude"
        os.write(master_fd, b"\x03")
        status = _wait_for_exit(pid, 3)
        output.extend(_read_available(master_fd))
        if status is None:
            os.kill(pid, signal.SIGTERM)
            child_reaped = _wait_for_exit(pid, 3) is not None
            raise AssertionError(
                "server ignored terminal Control-C; output="
                + output.decode(errors="replace")
            )
        child_reaped = True
        assert os.waitstatus_to_exitcode(status) in {0, 130}
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        if not child_reaped:
            waited_pid, _status = os.waitpid(pid, os.WNOHANG)
            if waited_pid != pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass
        if model_client is not None and model_client.poll() is None:
            model_client.terminate()
            try:
                model_client.wait(timeout=3)
            except subprocess.TimeoutExpired:
                model_client.kill()
                model_client.wait(timeout=3)


@pytest.mark.skipif(os.name != "posix", reason="PTY Control-C coverage requires POSIX")
@pytest.mark.parametrize("catalog_mode", ["immediate", "blocked", "error"])
@pytest.mark.parametrize("refresh_browser", [False, True])
def test_server_control_c_exits_across_catalog_refresh_states(tmp_path, catalog_mode, refresh_browser):
    _run_shutdown_case(
        tmp_path,
        catalog_mode=catalog_mode,
        refresh_browser=refresh_browser,
    )


@pytest.mark.skipif(os.name != "posix", reason="PTY Control-C coverage requires POSIX")
def test_server_reclaims_sigint_before_serving(tmp_path):
    _run_shutdown_case(
        tmp_path,
        catalog_mode="blocked",
        refresh_browser=True,
        swallow_sigint=True,
    )


@pytest.mark.skipif(os.name != "posix", reason="PTY Control-C coverage requires POSIX")
@pytest.mark.parametrize(
    "catalog_mode",
    ["cert-path-blocked", "ssl-context-blocked", "urlopen-blocked"],
)
def test_server_control_c_without_protection_during_catalog_tls_stages(tmp_path, catalog_mode):
    """Identify whether certificate/TLS initialization is the SIGINT trigger."""
    _run_shutdown_case(
        tmp_path,
        catalog_mode=catalog_mode,
        refresh_browser=True,
        skip_sigint_restore=True,
        audit_signals=True,
    )


@pytest.mark.skipif(os.name != "posix", reason="PTY Control-C coverage requires POSIX")
def test_server_control_c_with_browser_request_waiting_on_startup_catalog_lock(tmp_path):
    _run_shutdown_case(
        tmp_path,
        catalog_mode="urlopen-blocked",
        refresh_browser=True,
        skip_sigint_restore=True,
        block_on_model_request=True,
        audit_signals=True,
    )


@pytest.mark.skipif(os.name != "posix", reason="PTY Control-C coverage requires POSIX")
def test_server_control_c_unprotected_commit_comparison(tmp_path):
    """Portable probe used unchanged against revisions before and after 3ffe0c3."""
    _run_shutdown_case(
        tmp_path,
        catalog_mode="live",
        refresh_browser=True,
        skip_sigint_restore=True,
        audit_signals=True,
    )


@pytest.mark.skipif(os.name != "posix", reason="PTY Control-C coverage requires POSIX")
def test_server_control_c_with_many_workspace_threads_and_catalog_race(tmp_path):
    _run_shutdown_case(
        tmp_path,
        catalog_mode="urlopen-blocked",
        refresh_browser=True,
        skip_sigint_restore=True,
        block_on_model_request=True,
        audit_signals=True,
        workspace_count=24,
    )


@pytest.mark.skipif(os.name != "posix", reason="PTY Control-C coverage requires POSIX")
def test_server_control_c_after_uncaught_catalog_thread_failure(tmp_path):
    _run_shutdown_case(
        tmp_path,
        catalog_mode="thread-crash",
        refresh_browser=True,
        skip_sigint_restore=True,
        audit_signals=True,
        workspace_count=24,
    )
