"""Optional real-browser regression for Value number formatting."""

import subprocess
import tempfile
import os
import shutil
import json
import re

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
                viewport = page.locator(".worker-grid-viewport")
                viewport.focus()
                viewport.press("Enter")
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


def test_compact_value_spreadsheet_style_selection_theme_and_persistence_in_chromium():
    with tempfile.TemporaryDirectory(prefix="bullpen_value_spreadsheet_pw_") as workspace:
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

                for formula in ("=1", "=2"):
                    viewport.focus()
                    page.keyboard.type("=")
                    editor = page.get_by_role("textbox", name="Create value worker")
                    editor.fill(formula)
                    editor.press("Enter")
                    expect(page.locator(".worker-card")).to_have_count(1 if formula == "=1" else 2)
                    if formula == "=1":
                        viewport.focus()
                        viewport.press("ArrowRight")

                page.get_by_role("button", name="Small Rows").click()
                cards = page.locator(".worker-card")
                first = cards.nth(0)
                second = cards.nth(1)

                page.get_by_title("Worker colors").click()
                pill_checkbox = page.get_by_label("Use compact pill for value workers")
                expect(pill_checkbox).to_be_checked()
                pill_checkbox.uncheck()

                expect(first).to_have_class(re.compile(r"\bworker-card--spreadsheet\b"))
                expect(second).to_have_class(re.compile(r"\bworker-card--spreadsheet\b"))
                expect(first.locator(".worker-type-icon-host")).to_have_count(0)
                assert first.evaluate(
                    "element => getComputedStyle(element).backgroundColor"
                ) == "rgba(0, 0, 0, 0)"

                page.locator(".theme-select").select_option("light")
                expect(page.locator("html")).to_have_attribute("data-theme", "light")
                assert first.locator(".worker-card-compact-value").evaluate(
                    """element => {
                      const probe = document.createElement('span');
                      probe.style.color = 'var(--text-primary)';
                      document.body.appendChild(probe);
                      const expected = getComputedStyle(probe).color;
                      probe.remove();
                      return getComputedStyle(element).color === expected;
                    }"""
                )

                first.click(position={"x": 8, "y": 16})
                page.keyboard.press("Escape")
                expect(first).not_to_have_class(re.compile(r"\bworker-card--spreadsheet\b"))
                expect(first.locator(".worker-type-icon-host")).to_have_count(1)
                second.click(position={"x": 8, "y": 16}, modifiers=["Shift"])
                page.keyboard.press("Escape")
                expect(first).not_to_have_class(re.compile(r"\bworker-card--spreadsheet\b"))
                expect(second).not_to_have_class(re.compile(r"\bworker-card--spreadsheet\b"))
                expect(second.locator(".worker-type-icon-host")).to_have_count(1)

                viewport.focus()
                viewport.press("ArrowRight")
                expect(first).to_have_class(re.compile(r"\bworker-card--spreadsheet\b"))
                expect(second).to_have_class(re.compile(r"\bworker-card--spreadsheet\b"))

                config_path = os.path.join(workspace, ".bullpen", "config.json")
                with open(config_path, encoding="utf-8") as handle:
                    persisted = json.load(handle)
                assert persisted["worker_pill_styles"]["value"] is False

                page.reload()
                page.get_by_role("button", name="Workers").click()
                viewport = page.locator(".worker-grid-viewport")
                viewport.focus()
                viewport.press("ArrowRight")
                viewport.press("ArrowRight")
                cards = page.locator(".worker-card")
                expect(cards.nth(0)).to_have_class(re.compile(r"\bworker-card--spreadsheet\b"))
                expect(cards.nth(1)).to_have_class(re.compile(r"\bworker-card--spreadsheet\b"))
                page.get_by_title("Worker colors").click()
                expect(page.get_by_label("Use compact pill for value workers")).not_to_be_checked()
                browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_compact_value_spreadsheet_alignment_matrix_in_chromium():
    with tempfile.TemporaryDirectory(prefix="bullpen_value_alignment_pw_") as workspace:
        port = _free_port()
        proc = _start_server(workspace, port)
        try:
            base_url = f"http://127.0.0.1:{port}"
            _wait_for_server(base_url)
            bp_dir = os.path.join(workspace, ".bullpen")
            config_path = os.path.join(bp_dir, "config.json")
            layout_path = os.path.join(bp_dir, "layout.json")

            with open(config_path, encoding="utf-8") as handle:
                config = json.load(handle)
            config["grid"] = {
                **(config.get("grid") or {}),
                "rowHeight": 32,
                "rowHeights": {},
            }
            config["worker_pill_styles"]["value"] = False
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(config, handle, indent=2)
                handle.write("\n")

            with open(layout_path, encoding="utf-8") as handle:
                layout = json.load(handle)

            def value_slot(name, value, resolved, col, row, kind="general"):
                return {
                    "type": "value",
                    "name": name,
                    "value": value,
                    "value_type": "auto",
                    "resolved_value_type": resolved,
                    "format": {"kind": kind},
                    "state": "idle",
                    "task_queue": [],
                    "col": col,
                    "row": row,
                }

            layout["slots"] = [
                value_slot("direction", "west", "string", 0, 0),
                value_slot("", "femoral artery", "string", 1, 0),
                value_slot("", 1.02e24, "number", 2, 0),
                value_slot("", None, "null", 3, 0),
                value_slot("", 4504, "number", 0, 1),
                value_slot("left override", "tucson", "string", 1, 1, "string-left"),
                value_slot("right override", "east", "string", 2, 1, "string-right"),
            ]
            with open(layout_path, "w", encoding="utf-8") as handle:
                json.dump(layout, handle, indent=2)
                handle.write("\n")

            with sync_playwright() as playwright:
                browser = _launch_chromium(playwright)
                page = browser.new_page(locale="en-US")
                page.goto(base_url)
                page.get_by_role("button", name="Workers").click()
                cards = page.locator(".worker-card")
                expect(cards).to_have_count(7)
                viewport = page.locator(".worker-grid-viewport")
                viewport.focus()
                for _ in range(4):
                    viewport.press("ArrowRight")

                def alignment_for(card):
                    return card.evaluate(
                        """element => {
                          const value = element.querySelector('.worker-card-compact-value');
                          const cardRect = element.getBoundingClientRect();
                          const valueRect = value.getBoundingClientRect();
                          return {
                            align: getComputedStyle(value).textAlign,
                            identityCount: element.querySelectorAll('.worker-card-identity').length,
                            leftInset: valueRect.left - cardRect.left,
                            rightInset: cardRect.right - valueRect.right,
                          };
                        }"""
                    )

                labeled_string = alignment_for(cards.filter(has_text="direction").first)
                assert labeled_string["identityCount"] == 1
                assert labeled_string["align"] == "right"

                unlabeled_string = alignment_for(cards.filter(has_text="femoral artery").first)
                assert unlabeled_string["identityCount"] == 0
                assert unlabeled_string["align"] == "right"
                assert unlabeled_string["leftInset"] < 10
                assert unlabeled_string["rightInset"] < 10

                scientific_number = alignment_for(cards.filter(has_text="1.02e+24").first)
                assert scientific_number["identityCount"] == 0
                assert scientific_number["align"] == "right"
                assert scientific_number["rightInset"] < 10

                empty_value = alignment_for(cards.filter(has_text="Empty").first)
                assert empty_value["identityCount"] == 0
                assert empty_value["align"] == "right"
                assert empty_value["rightInset"] < 10

                unlabeled_number = alignment_for(cards.filter(has_text="4504").first)
                assert unlabeled_number["identityCount"] == 0
                assert unlabeled_number["align"] == "right"
                assert unlabeled_number["rightInset"] < 10

                explicit_left = alignment_for(cards.filter(has_text="left override").first)
                assert explicit_left["identityCount"] == 1
                assert explicit_left["align"] == "left"
                explicit_right = alignment_for(cards.filter(has_text="right override").first)
                assert explicit_right["identityCount"] == 1
                assert explicit_right["align"] == "right"
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


def test_drag_formula_translates_source_and_recalculates_in_chromium():
    with tempfile.TemporaryDirectory(prefix="bullpen_formula_drag_pw_") as workspace:
        port = _free_port()
        assert port != 5050
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

                page.get_by_role("gridcell", name="Empty cell at column 0, row 0").click()
                viewport.evaluate(
                    """(element) => {
                      const clipboard = new DataTransfer();
                      clipboard.setData('text/plain', '10\\r\\n20\\r\\n=SUM(A1:A2)');
                      element.dispatchEvent(new ClipboardEvent('paste', {
                        bubbles: true,
                        cancelable: true,
                        clipboardData: clipboard,
                      }));
                    }"""
                )
                formula_card = page.locator(".worker-card", has=page.locator(".worker-card-formula-badge"))
                expect(formula_card.locator(".worker-card-value-main")).to_have_text("30")

                # Empty grid cells are virtualized around the current selection.
                # Select B3 before resolving the drag target so this test drives
                # the same accessibility path a keyboard user would.
                viewport.focus()
                page.keyboard.press("ArrowRight")
                page.keyboard.press("ArrowDown")
                page.keyboard.press("ArrowDown")
                destination = page.get_by_role("gridcell", name="Empty cell at column 1, row 2")
                formula_card.drag_to(destination)

                expect(formula_card.locator(".worker-card-value-main")).to_have_text("0")
                expect(formula_card.locator(".worker-card-formula-badge")).to_have_text("fx")
                browser.close()

            with open(os.path.join(workspace, ".bullpen", "layout.json"), encoding="utf-8") as handle:
                layout = json.load(handle)
            formula = next(slot for slot in layout["slots"] if slot and slot.get("formula"))
            assert (formula["col"], formula["row"]) == (1, 2)
            assert formula["formula"]["source"] == "=SUM(B1:B2)"
            assert formula["value"] == 0
            assert [entry["value"] for entry in formula["history"]] == [30, 0]
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_sparse_row_column_formula_and_two_window_revision_sync_in_chromium():
    with tempfile.TemporaryDirectory(prefix="bullpen_formula_sync_pw_") as workspace:
        port = _free_port()
        proc = _start_server(workspace, port)
        try:
            base_url = f"http://127.0.0.1:{port}"
            _wait_for_server(base_url)

            with sync_playwright() as playwright:
                browser = _launch_chromium(playwright)
                first = browser.new_page(locale="en-US")
                second = browser.new_page(locale="en-US")
                for page in (first, second):
                    page.goto(base_url)
                    page.get_by_role("button", name="Workers").click()

                first_viewport = first.locator(".worker-grid-viewport")
                first.get_by_role("gridcell", name="Empty cell at column 0, row 0").click()
                first_viewport.evaluate(
                    """(element) => {
                      const clipboard = new DataTransfer();
                      clipboard.setData('text/plain', '2\\t=A1*3');
                      element.dispatchEvent(new ClipboardEvent('paste', {
                        bubbles: true,
                        cancelable: true,
                        clipboardData: clipboard,
                      }));
                    }"""
                )
                expect(first.locator(".worker-card-value-main").nth(1)).to_have_text("6")
                expect(second.locator(".worker-card-value-main").nth(1)).to_have_text("6")

                first.locator(".worker-card-value-main").nth(0).click()
                editor = first.get_by_role("textbox", name="Edit value", exact=True)
                editor.fill("4")
                editor.press("Enter")
                expect(first.locator(".worker-card-value-main").nth(1)).to_have_text("12")
                expect(second.locator(".worker-card-value-main").nth(1)).to_have_text("12")

                first_viewport.focus()
                for _ in range(8):
                    first_viewport.press("ArrowRight")
                for _ in range(31):
                    first_viewport.press("ArrowDown")
                first.keyboard.type("=")
                formula_editor = first.get_by_role("textbox", name="Create value worker")
                formula_editor.fill("=ROW()*100+COLUMN()")
                formula_editor.press("Enter")
                sparse_card = first.locator(
                    ".worker-card",
                    has=first.locator(".worker-card-formula-badge"),
                ).last
                expect(sparse_card.locator(".worker-card-value-main")).to_have_text("3209")
                second_viewport = second.locator(".worker-grid-viewport")
                second_viewport.focus()
                for _ in range(8):
                    second_viewport.press("ArrowRight")
                for _ in range(31):
                    second_viewport.press("ArrowDown")
                expect(second.locator(".worker-card-value-main", has_text="3209")).to_be_visible()
                browser.close()

            with open(os.path.join(workspace, ".bullpen", "layout.json"), encoding="utf-8") as handle:
                layout = json.load(handle)
            sparse = next(
                slot for slot in layout["slots"]
                if slot and slot.get("formula", {}).get("source") == "=ROW()*100+COLUMN()"
            )
            assert (sparse["col"], sparse["row"]) == (8, 31)
            assert sparse["value"] == 3209
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_two_window_volatile_activation_coalesces_without_history_in_chromium():
    with tempfile.TemporaryDirectory(prefix="bullpen_formula_volatile_pw_") as workspace:
        port = _free_port()
        proc = _start_server(workspace, port)
        try:
            base_url = f"http://127.0.0.1:{port}"
            _wait_for_server(base_url)
            layout_path = os.path.join(workspace, ".bullpen", "layout.json")

            with sync_playwright() as playwright:
                browser = _launch_chromium(playwright)
                setup = browser.new_page(locale="en-US")
                setup.goto(base_url)
                setup.get_by_role("button", name="Workers").click()
                viewport = setup.locator(".worker-grid-viewport")
                viewport.focus()
                setup.keyboard.type("=")
                editor = setup.get_by_role("textbox", name="Create value worker")
                editor.fill("=NOW()")
                editor.press("Enter")
                expect(setup.locator(".worker-card-formula-badge")).to_have_text("fx")
                setup.close()

                with open(layout_path, encoding="utf-8") as handle:
                    stale_layout = json.load(handle)
                formula = next(slot for slot in stale_layout["slots"] if slot and slot.get("formula"))
                formula["value"] = "2000-01-01T00:00:00Z"
                formula["formula_state"]["calculated_at"] = "2000-01-01T00:00:00Z"
                history_before = list(formula.get("history", []))
                revision_before = stale_layout["workspace_revision"]
                with open(layout_path, "w", encoding="utf-8") as handle:
                    json.dump(stale_layout, handle, indent=2)
                    handle.write("\n")

                first = browser.new_page(locale="en-US")
                second = browser.new_page(locale="en-US")
                first.goto(base_url)
                second.goto(base_url)
                for page in (first, second):
                    page.get_by_role("button", name="Workers").click()
                first.wait_for_timeout(2100)
                first.bring_to_front()
                first.evaluate("window.dispatchEvent(new Event('focus'))")
                second.bring_to_front()
                second.evaluate("window.dispatchEvent(new Event('focus'))")
                for page in (first, second):
                    expect(page.locator(".worker-card-value-main")).not_to_have_text("2000-01-01T00:00:00Z")

                with open(layout_path, encoding="utf-8") as handle:
                    activated = json.load(handle)
                activated_formula = next(slot for slot in activated["slots"] if slot and slot.get("formula"))
                assert activated["workspace_revision"] == revision_before + 1
                assert activated_formula["history"] == history_before
                assert activated_formula["value"] != "2000-01-01T00:00:00Z"
                browser.close()
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
