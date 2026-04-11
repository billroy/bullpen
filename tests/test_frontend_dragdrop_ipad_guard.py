"""Regression checks for iPad-safe drag/drop behavior."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK_DND_MIME = "application/x-bullpen-task-id"


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_task_drag_uses_custom_mime_and_plaintext_fallback():
    task_card = _read("static/components/TaskCard.js")
    left_pane = _read("static/components/LeftPane.js")
    assert TASK_DND_MIME in task_card
    assert "setData(TASK_DND_MIME, this.task.id)" in task_card
    assert TASK_DND_MIME in left_pane
    assert "setData(TASK_DND_MIME, taskId)" in left_pane


def test_drop_targets_prevent_default_and_read_custom_mime():
    kanban = _read("static/components/KanbanTab.js")
    worker = _read("static/components/WorkerCard.js")
    left_pane = _read("static/components/LeftPane.js")

    assert "@drop.prevent=\"onDrop($event, col.key)\"" in kanban
    assert "e.preventDefault();" in kanban
    assert "getData(TASK_DND_MIME) || e.dataTransfer.getData('text/plain')" in kanban

    assert "@drop.prevent=\"onDrop\"" in worker
    assert "getData(TASK_DND_MIME) || e.dataTransfer.getData('text/plain')" in worker

    assert "e.preventDefault();" in left_pane
    assert "getData(TASK_DND_MIME) || e.dataTransfer.getData('text/plain')" in left_pane


def test_draggable_ticket_styles_disable_text_selection():
    css = _read("static/style.css")
    assert ".task-card[draggable=\"true\"]" in css
    assert ".inbox-item[draggable=\"true\"]" in css
    assert "-webkit-touch-callout: none;" in css
