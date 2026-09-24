"""Regression checks for the New Ticket column selector."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_task_create_modal_accepts_columns_and_filters_worker_columns():
    text = _read("static/components/TaskCreateModal.js")
    assert "props: ['visible', 'columns']" in text
    assert "const workerColumns = new Set(['assigned', 'in_progress']);" in text
    assert ".filter(col => col?.key && !workerColumns.has(col.key))" in text
    assert "return columns.length ? columns : [{ key: 'inbox', label: 'Inbox' }];" in text


def test_task_create_modal_renders_column_selector_and_defaults_to_inbox():
    text = _read("static/components/TaskCreateModal.js")
    assert "Column" in text
    assert '<select class="form-select" v-model="status">' in text
    assert '<option v-for="col in writableColumns" :key="col.key" :value="col.key">{{ col.label }}</option>' in text
    assert "if (this.writableColumns.some(col => col.key === 'inbox')) return 'inbox';" in text


def test_task_create_modal_persists_selected_column_and_emits_status():
    text = _read("static/components/TaskCreateModal.js")
    assert "window.localStorage?.getItem('bullpen.newTicket.status')" in text
    assert "window.localStorage?.setItem('bullpen.newTicket.status', this.status || this.defaultStatus);" in text
    assert "this.persistStatus();" in text
    assert "status: this.status," in text


def test_app_passes_columns_to_task_create_modal():
    text = _read("static/app.js")
    assert ':columns="state.config.columns"' in text
