"""Optional Playwright browser regression for the Notification worker dialog."""

import os
import socket
import subprocess
import sys
import tempfile
import time

import pytest


pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402


def _free_port():
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", 0))
            except PermissionError:
                pytest.skip("local port binding is not permitted in this sandbox")
            port = sock.getsockname()[1]
        if port != 5050:
            return port


def _wait_for_server(url, timeout=10.0):
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError(f"server did not start: {url}")


def _wait_for_synthetic_task(workspace, worker_name, status, timeout=5.0):
    from server.tasks import list_tasks

    bp_dir = os.path.join(workspace, ".bullpen")
    prefix = f"[Auto] {worker_name} - manual - "
    deadline = time.time() + timeout
    matches = []
    while time.time() < deadline:
        matches = [
            task for task in list_tasks(bp_dir)
            if task.get("synthetic_run") is True
            and task.get("trigger_kind") == "manual"
            and str(task.get("title", "")).startswith(prefix)
        ]
        if matches and matches[-1].get("status") == status:
            return matches[-1]
        time.sleep(0.05)
    return matches[-1] if matches else None


def _start_server(workspace, port):
    env = os.environ.copy()
    env["HOME"] = os.path.join(workspace, "home")
    os.makedirs(env["HOME"], exist_ok=True)
    return subprocess.Popen(
        [
            sys.executable,
            "bullpen.py",
            "--workspace",
            workspace,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-browser",
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_notification_dialog_controls_and_run_menu_with_playwright():
    with tempfile.TemporaryDirectory(prefix="bullpen_notify_pw_") as workspace:
        port = _free_port()
        proc = _start_server(workspace, port)
        try:
            base_url = f"http://127.0.0.1:{port}"
            _wait_for_server(base_url)

            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception as exc:
                    if "Executable doesn't exist" in str(exc):
                        pytest.skip("Playwright browser binaries are not installed")
                    raise
                page = browser.new_page()
                page.goto(base_url)

                page.get_by_role("button", name="Workers").click()
                page.get_by_role("gridcell", name="Empty cell at column 0, row 0").get_by_role(
                    "button", name="…"
                ).click()
                page.get_by_role("button", name="Add Worker").click()
                page.get_by_role("tab", name="Notification").click()
                page.get_by_text("Blank notification worker", exact=True).click()

                modal = page.locator(".modal.modal-wide")
                modal.get_by_role("textbox", name="Name", exact=True).fill("Playwright Notify")
                modal.get_by_role("checkbox", name="Toast", exact=True).uncheck()
                modal.get_by_placeholder("{ticket.title} reached {worker.name}.").fill(
                    "{ticket.title} toast {worker.name} {workspace.name}"
                )
                modal.locator("select").nth(0).select_option("warning")
                modal.locator('input[type="number"]').nth(0).fill("12345")
                modal.get_by_role("checkbox", name="Speech", exact=True).check()
                modal.get_by_placeholder("{ticket.title} is ready.").fill(
                    "Speak {ticket.priority} {ticket.title}"
                )
                modal.get_by_label("Engine").select_option("kokoro")
                modal.get_by_label("Voice").select_option("af_bella")
                modal.locator('input[type="number"]').nth(1).fill("1.4")
                modal.locator('input[type="number"]').nth(2).fill("0.6")
                modal.get_by_role("checkbox", name="Sound", exact=True).check()
                modal.get_by_label("Effect").select_option("warning")
                modal.locator('input[type="number"]').nth(3).fill("4")
                modal.locator('input[type="number"]').nth(4).fill("750")
                modal.locator('input[type="number"]').nth(5).fill("0.7")
                modal.get_by_role("checkbox", name="Screen flash", exact=True).check()
                modal.get_by_role("button", name="Add flash step").click()
                flash_inputs = modal.locator(".shell-env-row input")
                expect_count = flash_inputs.count()
                assert expect_count == 4
                flash_inputs.nth(0).fill("#00ff88")
                flash_inputs.nth(1).fill("220")
                flash_inputs.nth(2).fill("#0044ff")
                flash_inputs.nth(3).fill("330")
                modal.locator(".shell-env-row button").nth(1).click()
                modal.get_by_label("Opacity").fill("0.45")
                modal.get_by_label("Cooldown (ms)").fill("2500")
                modal.get_by_label("Dedupe window (ms)").fill("9000")
                trigger = modal.get_by_label("Input Trigger")
                trigger.select_option("on_queue")
                modal.get_by_label("Pass tickets to").select_option("review")
                trigger.select_option("at_time")
                modal.get_by_label("Trigger Time (HH:MM, local)").fill("09:30")
                modal.get_by_label("Repeat every day").check()
                trigger.select_option("on_interval")
                modal.get_by_label("Interval (minutes)").fill("15")
                trigger.select_option("on_drop")
                modal.get_by_role("button", name="Save").click()

                page.evaluate("""
                    window.BULLPEN_KOKORO_LOADER = async () => ({
                      KokoroTTS: {
                        from_pretrained: async () => ({
                          generate: async () => ({
                            toBlob: () => new Blob(['fake-audio'], { type: 'audio/wav' })
                          })
                        })
                      }
                    });
                    HTMLMediaElement.prototype.play = function () {
                      setTimeout(() => {
                        if (typeof this.onended === 'function') this.onended();
                        this.dispatchEvent(new Event('ended'));
                      }, 0);
                      return Promise.resolve();
                    };
                """)
                page.locator(".worker-card", has_text="Playwright Notify").hover()
                page.locator(".worker-card", has_text="Playwright Notify").locator(".worker-menu-btn").click()
                page.get_by_role("button", name="Run").click()
                synthetic = _wait_for_synthetic_task(workspace, "Playwright Notify", "review")
                assert synthetic is not None
                assert synthetic["assigned_to"] == ""
                assert synthetic["title"].startswith("[Auto] Playwright Notify - manual - ")
                assert not page.get_by_text("notifies existing tickets only").is_visible()

                browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
