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
    assert 'aria-label="Formula value">fx' in card
    assert "this.worker?.formula?.source || this.storedValueText" in card
    assert "formula_source: String(parsed.value).trim()" in card
    assert "this.formulaError" in card
