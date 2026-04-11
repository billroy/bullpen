"""Regression checks for ticket title icon rendering."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_kanban_ticket_card_title_renders_ticket_icon():
    text = _read("static/components/TaskCard.js")
    assert "class=\"task-card-title\"" in text
    assert "class=\"ticket-type-icon ticket-type-icon--card\"" in text
    assert "data-lucide=\"tag\"" in text
    assert "class=\"task-card-title-text\"" in text


def test_ticket_list_title_renders_ticket_icon():
    text = _read("static/components/KanbanTab.js")
    assert "class=\"ticket-list-title-wrap\"" in text
    assert "class=\"ticket-type-icon ticket-type-icon--list\"" in text
    assert "data-lucide=\"tag\"" in text
    assert "class=\"ticket-list-title-text\"" in text


def test_ticket_detail_header_renders_ticket_icon():
    text = _read("static/components/TaskDetailPanel.js")
    assert "class=\"detail-title-wrap\"" in text
    assert "class=\"ticket-type-icon ticket-type-icon--detail\"" in text
    assert "data-lucide=\"tag\"" in text
    assert "renderLucideIcons(this.$el);" in text


def test_ticket_icon_styles_exist():
    text = _read("static/style.css")
    assert ".ticket-type-icon" in text
    assert ".ticket-type-icon--card" in text
    assert ".ticket-type-icon--list" in text
    assert ".ticket-type-icon--detail" in text
    assert ".task-card-title-text" in text
    assert ".ticket-list-title-wrap" in text
    assert ".ticket-list-title-text" in text
    assert ".detail-title-wrap" in text
