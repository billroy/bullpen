"""Regression checks for slash-splitting in left-pane quick ticket create."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_leftpane_quick_create_splits_title_and_description_at_first_slash():
    text = _read("static/components/LeftPane.js")
    assert "const slashIdx = text.indexOf('/');" in text
    assert "title: text.slice(0, slashIdx).trim()," in text
    assert "description: text.slice(slashIdx + 1).trim()," in text
    assert "this.$emit('quick-create-task', payload);" in text


def test_app_quick_create_accepts_payload_with_description():
    text = _read("static/app.js")
    assert "function quickCreateTask(payload)" in text
    assert "const title = typeof payload === 'string' ? payload.trim() : (payload?.title || '').trim();" in text
    assert "const description = typeof payload === 'string' ? '' : (payload?.description || '').trim();" in text
    assert "socket.emit('task:create', _wsData({ title, type: 'task', priority: 'normal', tags: [], description }));" in text


def test_leftpane_quick_create_placeholder_uses_bug_template_text():
    text = _read("static/components/LeftPane.js")
    assert 'placeholder="title&#10;&#10;Type: task&#10;&#10;Priority: normal&#10;&#10;## Description&#10;&#10;description"' in text
