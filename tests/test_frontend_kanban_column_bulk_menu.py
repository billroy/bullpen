"""Regression checks for Kanban column bulk action menus."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_kanban_column_header_uses_inline_count_and_action_menu():
    text = _read("static/components/KanbanTab.js")

    assert "class=\"column-count-inline\"" in text
    assert "({{ columnTasks(col.key).length }})" in text
    assert "class=\"btn-icon column-menu-btn\"" in text
    assert "data-lucide=\"more-horizontal\"" in text
    assert "Move all to..." in text
    assert "Archive all" in text
    assert "class=\"column-count\"" not in text
    assert "column-archive-btn" not in text


def test_kanban_column_menu_emits_bulk_events():
    text = _read("static/components/KanbanTab.js")

    assert "'move-column-tasks'" in text
    assert "'archive-column-tasks'" in text
    assert "moveTargetColumns(sourceKey)" in text
    assert "$emit('move-column-tasks', { fromStatus: source.key, toStatus: target.key })" in text
    assert "$emit('archive-column-tasks', { status: col.key })" in text


def test_app_wires_column_bulk_events_to_existing_ticket_events():
    text = _read("static/app.js")

    assert "@move-column-tasks=\"moveColumnTasks\"" in text
    assert "@archive-column-tasks=\"archiveColumnTasks\"" in text
    assert "function moveColumnTasks({ fromStatus, toStatus })" in text
    assert "socket.emit('task:update', _wsData({ id: task.id, status: toStatus }))" in text
    assert "function archiveColumnTasks({ status })" in text
    assert "socket.emit('task:archive', _wsData({ id: task.id }))" in text


def test_column_bulk_menu_styles_exist():
    text = _read("static/style.css")

    assert ".column-count-inline" in text
    assert ".column-actions" in text
    assert ".column-menu-btn" in text
    assert ".column-action-menu" in text
    assert "position: fixed;" in text
