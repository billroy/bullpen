"""Optional real-browser regression for Value number formatting."""

import subprocess
import tempfile
import os
import shutil
import json

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


@pytest.mark.parametrize(
    ("formula", "expected_text", "expected_value"),
    [
        ("=2+2*3", "8", 8),
        ("=SUM(C36:C37)", "0", 0),
        ('="Hello, world: [ok] (v1)! #50% / path?"', "Hello, world: [ok] (v1)! #50% / path?", "Hello, world: [ok] (v1)! #50% / path?"),
    ],
)
def test_formula_entry_is_reeditable_without_change_in_chromium(formula, expected_text, expected_value):
    """Formula source must survive a compact-editor double-click/Enter round trip."""
    with tempfile.TemporaryDirectory(prefix="bullpen_formula_add_pw_") as workspace:
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

                viewport = page.locator(".worker-grid-viewport")
                viewport.focus()
                page.keyboard.type("=")
                editor = page.get_by_role("textbox", name="Create value worker")
                editor.fill(formula)
                expect(editor).to_have_value(formula)
                editor.press("Enter")

                card = page.locator(".worker-card", has=page.locator(".worker-card-formula-badge"))
                expect(card.locator(".worker-card-value-main")).to_have_text(expected_text)
                expect(card.locator(".worker-card-formula-badge")).to_have_text("fx")

                page.get_by_role("button", name="Small Rows", exact=True).click()
                compact_value = page.get_by_role("button", name="Edit name and value", exact=True)
                expect(compact_value).to_have_text(expected_text)
                compact_value.dblclick()
                compact_editor = page.get_by_role("textbox", name="Edit name and value", exact=True)
                expect(compact_editor).to_have_value(formula)
                compact_editor.press("Enter")
                expect(compact_value).to_have_text(expected_text)
                browser.close()

            with open(os.path.join(workspace, ".bullpen", "layout.json"), encoding="utf-8") as handle:
                layout = json.load(handle)
            worker = next(slot for slot in layout["slots"] if slot and slot.get("type") == "value")
            assert worker["value"] == expected_value
            assert worker["formula"] == {"source": formula, "version": 1}
            assert worker["formula_state"]["status"] == "ok"
            assert len(worker["history"]) == 1
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_scalar_and_rectangular_system_clipboard_paste_in_chromium():
    with tempfile.TemporaryDirectory(prefix="bullpen_value_paste_pw_") as workspace:
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
                viewport = page.locator(".worker-grid-viewport")

                def dispatch_paste(text):
                    viewport.evaluate(
                        """(element, value) => {
                          const clipboard = new DataTransfer();
                          clipboard.setData('text/plain', value);
                          element.dispatchEvent(new ClipboardEvent('paste', {
                            bubbles: true,
                            cancelable: true,
                            clipboardData: clipboard,
                          }));
                        }""",
                        text,
                    )

                page.get_by_role("gridcell", name="Empty cell at column 0, row 0").click()
                dispatch_paste("42")
                expect(page.locator(".toast-message", has_text="Pasted 1×1 range: 1 Value created")).to_be_visible()
                expect(page.locator(".worker-card-value-main")).to_have_count(1)
                expect(page.locator(".worker-card-value-main").nth(0)).to_have_text("42")

                viewport.focus()
                viewport.press("ArrowRight")
                viewport.press("ArrowRight")
                viewport.press("ArrowDown")
                viewport.press("ArrowDown")
                dispatch_paste("1\t\t3\r\n4\t5\t6\r\n")
                expect(page.locator(
                    ".toast-message", has_text="Pasted 2×3 range: 5 Values created, 1 blank cell skipped"
                )).to_be_visible()
                expect(page.locator(".worker-card-value-main")).to_have_count(6)
                assert page.locator(".worker-card-value-main").all_text_contents() == ["42", "1", "3", "4", "5", "6"]
                browser.close()

            with open(os.path.join(workspace, ".bullpen", "layout.json"), encoding="utf-8") as handle:
                layout = json.load(handle)
            values = [slot for slot in layout["slots"] if slot and slot.get("type") == "value"]
            assert [(slot["col"], slot["row"]) for slot in values] == [
                (0, 0), (2, 2), (4, 2), (2, 3), (3, 3), (4, 3),
            ]
            assert all(slot["resolved_value_type"] == "number" for slot in values)
            assert all(len(slot["history"]) == 1 for slot in values)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
