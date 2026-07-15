"""Regression checks for copying ticket IDs from the detail panel."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_task_detail_has_copy_id_button_and_clipboard_handler():
    text = _read("static/components/TaskDetailPanel.js")
    assert "Copy ID" in text
    assert "copyId" in text
    assert "navigator.clipboard.writeText(id)" in text
    assert "copyIdFallback" in text
    assert "Ticket ID copied" in text


def test_task_detail_copy_id_toast_is_wired_to_app():
    detail = _read("static/components/TaskDetailPanel.js")
    app = _read("static/app.js")

    assert "'toast'" in detail
    assert "@toast=\"addToast\"" in app


def test_task_detail_assign_ticket_dropdown_reuses_assign_task():
    detail = _read("static/components/TaskDetailPanel.js")
    app = _read("static/app.js")
    css = _read("static/style.css")

    assert "'workers'" in detail
    assert "'assign'" in detail
    assert "assignableWorkers()" in detail
    assert "Assign Ticket" in detail
    assert "@change=\"assignTicket\"" in detail
    assert "this.$emit('assign', { taskId: this.task.id, slot });" in detail
    assert "workerAcceptsTaskDrop(worker)" in detail
    assert "isValueWorker(worker)" in detail
    assert "isEvalWorker(worker)" in detail
    assert "isUnknownWorkerType(worker)" in detail
    assert ":workers=\"state.layout?.slots || []\"" in app
    assert "@assign=\"assignTask($event.taskId, $event.slot)\"" in app
    assert ".detail-assign-ticket" in css
