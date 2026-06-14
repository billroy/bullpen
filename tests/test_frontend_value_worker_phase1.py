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
