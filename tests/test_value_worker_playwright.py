"""Optional real-browser regression for Value number formatting."""

import subprocess
import tempfile
import os
import shutil

import pytest


pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from tests.test_notification_worker_playwright import (  # noqa: E402
    _free_port,
    _start_server,
    _wait_for_server,
)


def _launch_chromium(playwright):
    try:
        return playwright.chromium.launch()
    except Exception as exc:
        if "Executable doesn't exist" not in str(exc):
            raise
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    executable = next((path for path in candidates if path and os.path.isfile(path)), None)
    if not executable:
        pytest.skip("Playwright and system Chromium browser binaries are not installed")
    return playwright.chromium.launch(executable_path=executable)


def test_value_number_formatting_and_string_preservation_in_chromium():
    with tempfile.TemporaryDirectory(prefix="bullpen_value_pw_") as workspace:
        port = _free_port()
        proc = _start_server(workspace, port)
        try:
            base_url = f"http://127.0.0.1:{port}"
            _wait_for_server(base_url)

            with sync_playwright() as playwright:
                browser = _launch_chromium(playwright)
                page = browser.new_page(locale="en-US")
                page.goto(base_url)

                page.get_by_role("button", name="Workers").click()
                page.get_by_role("gridcell", name="Empty cell at column 0, row 0").get_by_role(
                    "button", name="…"
                ).click()
                page.get_by_role("button", name="Add Worker").click()
                page.get_by_role("tab", name="Value").click()
                page.get_by_text("Blank value worker", exact=True).click()

                modal = page.locator(".modal.modal-wide")
                modal.get_by_role("textbox", name="Name", exact=True).fill("Revenue")
                modal.get_by_role("textbox", name="Value", exact=True).fill("3458734893")
                modal.get_by_label("Format").select_option("number")
                modal.get_by_label("Decimal Places").select_option(label="Auto")
                modal.get_by_label("Use thousands separator").check()
                modal.get_by_role("button", name="Save").click()

                card = page.locator(".worker-card", has_text="Revenue")
                value = card.locator(".worker-card-value-main")
                expect(value).to_have_text("3,458,734,893")
                assert value.evaluate("element => getComputedStyle(element).textAlign") == "right"

                card.hover()
                card.locator(".worker-menu-btn").click()
                page.get_by_role("button", name="Edit").click()
                modal = page.locator(".modal.modal-wide")
                modal.get_by_label("Type").select_option("string")
                modal.get_by_role("textbox", name="Value", exact=True).fill("12000")
                modal.get_by_label("Format").select_option("number")
                modal.get_by_role("button", name="Save").click()

                expect(value).to_have_text("12000")
                browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
