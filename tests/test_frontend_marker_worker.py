"""Regression checks for Marker worker frontend wiring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_marker_worker_type_is_registered_in_shared_utils():
    text = _read("static/utils.js")
    assert "'marker'" in text
    assert "function isMarkerWorker(worker)" in text
    assert "if (isMarkerWorker(worker)) return 'square-dot';" in text
    assert "if (isMarkerWorker(worker)) return 'Marker';" in text


def test_marker_worker_create_flow_and_modal_fields_exist():
    tab = _read("static/components/BullpenTab.js")
    modal = _read("static/components/WorkerConfigModal.js")

    assert "libraryMode === 'marker'" in tab
    assert "@click=\"addMarkerWorker()\"" in tab
    assert "type: 'marker'," in tab
    assert "note: ''" in tab
    assert "icon: 'square-dot'" in tab
    assert "color: 'marker'" in tab
    assert "Eval</span>" not in tab

    assert "isMarker()" in modal
    assert "<span v-if=\"isMarker\" class=\"worker-type-badge\">Marker</span>" in modal
    assert "Pass tickets to" in modal
    assert "placeholder=\"square-dot\"" in modal
    assert "placeholder=\"marker or #c8b38c\"" in modal


def test_marker_worker_card_renders_note_without_output_focus_affordances():
    text = _read("static/components/WorkerCard.js")
    style = _read("static/style.css")

    assert "v-else-if=\"isMarker\" class=\"worker-card-empty worker-card-empty--marker\"" in text
    assert "markerNote()" in text
    assert "if (this.isMarker) return 'Marker';" in text
    assert ".worker-card-empty--marker {" in style
    assert ".worker-card-note {" in style
