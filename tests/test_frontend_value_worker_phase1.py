"""Source-level checks for initial value worker frontend wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_value_worker_type_metadata_is_registered():
    text = (ROOT / "static" / "utils.js").read_text()

    assert "value: '#86efac'" in text
    assert "worker?.type === 'value'" in text
    assert "'value', 'eval'" in text
    assert "function isValueWorker(worker)" in text
    assert "return 'variable';" in text
    assert "return 'Value';" in text


def test_grid_geometry_exposes_cell_reference_helpers_used_by_bullpen_tab():
    geometry = (ROOT / "static" / "gridGeometry.js").read_text()
    tab = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert "function parseCellRef(text)" in geometry
    assert "function colLabel(col)" in geometry
    assert "function rowLabel(row)" in geometry
    assert "function coordToCellRef(coord)" in geometry
    assert "parseCellRef," in geometry
    assert "coordToCellRef," in geometry
    assert "return GridGeometry.parseCellRef(text);" in tab
    assert "return GridGeometry.colLabel(col);" in tab
    assert "return GridGeometry.rowLabel(row);" in tab


def test_value_worker_can_be_created_from_library():
    text = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert "libraryMode === 'value'" in text
    assert 'data-lucide="variable"' in text
    assert "Blank value worker" in text
    assert "addValueWorker()" in text
    assert "type: 'value'" in text
    assert "value_type: 'auto'" in text


def test_value_worker_config_modal_has_value_fields_only():
    text = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text()

    assert "isValue()" in text
    assert '<span v-if="isValue" class="worker-type-badge">Value</span>' in text
    assert '<template v-if="isValue">' in text
    assert 'v-model="form.value"' in text
    assert 'v-model="form.value_type"' in text
    assert 'v-model="form.format.kind"' in text
    assert 'v-if="!isService && !isValue"' in text
    value_save_branch = text.split("if (this.isValue) {", 1)[1].split("} else if (this.isMarker || this.isNotification) {", 1)[0]
    assert "delete fields.activation;" in value_save_branch
    assert "delete fields.disposition;" in value_save_branch
    assert "delete fields.notification;" in value_save_branch


def test_value_worker_card_displays_value_without_run_controls():
    text = (ROOT / "static" / "components" / "WorkerCard.js").read_text()

    assert 'v-else-if="isValue" class="worker-card-value"' in text
    assert "{{ valueCellRef || 'Value' }}" in text
    assert "{{ valueDisplay || 'Empty' }}" in text
    assert "return isValueWorker(this.worker);" in text
    assert "if (this.isValue) return false;" in text
    assert "return !this.isMarker && !this.isValue && !this.isEval && !this.isUnknownType;" in text
    assert "window.GridGeometry?.coordToCellRef?.(this.worker)" in text


def test_value_worker_card_styles_exist():
    text = (ROOT / "static" / "style.css").read_text()

    assert ".worker-card-value {" in text
    assert ".worker-card-value-meta {" in text
    assert ".worker-card-value-main {" in text
