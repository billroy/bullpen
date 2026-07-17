from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return (ROOT / path).read_text()


def test_value_formula_modal_exposes_source_status_and_server_save_path():
    modal = _read("static/components/WorkerConfigModal.js")
    app = _read("static/app.js")
    assert 'v-model="form.formula_source"' in modal
    assert "worker.formula_state?.status === 'error'" in modal
    assert "socket.emit('formula:set'" in app
    assert "delete patch.value" in app


def test_value_card_renders_fx_error_and_edits_formula_source():
    card = _read("static/components/WorkerCard.js")
    assert "'Formula value is stale' : 'Formula value'" in card
    assert "formula_state?.derived_stale === true" in card
    assert "this.worker?.formula?.source || this.storedValueText" in card
    assert "formula_source: String(parsed.value).trim()" in card
    assert "this.formulaError" in card


def test_formula_activation_and_monotonic_layout_revisions_are_wired():
    app = _read("static/app.js")
    assert "function activateStaleFormulas" in app
    assert "socket.emit('formula:activate', { workspaceId: wsId });" in app
    assert "window.addEventListener('focus', activateVisibleFormulas);" in app
    assert "document.addEventListener('visibilitychange', activateVisibleFormulas);" in app
    assert "incomingRevision <= ws.workspaceRevision" in app
