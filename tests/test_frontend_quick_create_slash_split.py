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
    assert "this.$emit('quick-create-task', payload);\n      this.quickCreateText = '';" not in text


def test_app_quick_create_accepts_payload_with_description():
    text = _read("static/app.js")
    assert "function quickCreateTask(payload)" in text
    assert "const title = typeof payload === 'string' ? payload.trim() : (payload?.title || '').trim();" in text
    assert "const description = typeof payload === 'string' ? '' : (payload?.description || '').trim();" in text
    assert "pendingQuickCreates.push({ title, description });" in text
    assert "socket.emit('task:create', _wsData({ title, type: 'task', priority: 'normal', tags: [], description }));" in text


def test_quick_create_input_clears_only_after_create_ack():
    app = _read("static/app.js")
    left = _read("static/components/LeftPane.js")
    assert "const quickCreateClearToken = ref(0);" in app
    assert "quickCreateClearToken.value++;" in app
    assert ':quick-create-clear-token="quickCreateClearToken"' in app
    assert "quickCreateClearToken() {" in left
    assert "this.quickCreateText = '';" in left


def test_leftpane_quick_create_placeholder_uses_compact_prompt_text():
    text = _read("static/components/LeftPane.js")
    assert 'placeholder="enter title/description"' in text
