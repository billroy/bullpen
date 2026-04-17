"""Regression checks for top-toolbar command-bar behavior."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_top_toolbar_routes_slash_prefixed_entries_to_command_bar_event():
    text = _read("static/components/TopToolbar.js")
    assert "'run-command-bar'," in text
    assert "if (text.startsWith('/')) {" in text
    assert "this.$emit('run-command-bar', text);" in text
    assert "this.quickCreateText = '';" in text
    assert "this.$emit('quick-create-task', payload);" in text


def test_app_wires_top_toolbar_command_event_to_run_command_bar_handler():
    text = _read("static/app.js")
    assert "@run-command-bar=\"runCommandBar\"" in text
    assert "function runCommandBar(input) {" in text


def test_command_bar_supports_ticket_and_ui_commands():
    text = _read("static/app.js")
    assert "if (command === 'new' || command === 'ticket' || command === 'create') {" in text
    assert "if (command === 'tab') {" in text
    assert "if (command === 'view') {" in text
    assert "if (command === 'scope') {" in text
    assert "if (command === 'theme') {" in text
    assert "if (command === 'ambient') {" in text
    assert "if (command === 'volume') {" in text
    assert "addToast('Commands: /new, /ticket, /tab, /view, /scope, /left, /theme, /ambient, /volume');" in text
