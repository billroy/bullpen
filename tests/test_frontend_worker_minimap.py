"""Regression checks for worker minimap visibility controls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_worker_minimap_defaults_collapsed_and_is_app_controlled():
    text = _read("static/app.js")
    assert "const workerMinimapCollapsed = ref(true);" in text
    assert ":worker-minimap-collapsed=\"workerMinimapCollapsed\"" in text
    assert ":minimap-collapsed=\"workerMinimapCollapsed\"" in text
    assert "@set-minimap-collapsed=\"setWorkerMinimapCollapsed\"" in text


def test_top_toolbar_exposes_minimap_toggle():
    text = _read("static/components/TopToolbar.js")
    assert "workerMinimapCollapsed" in text
    assert "'set-worker-minimap-collapsed'" in text
    assert "onToggleWorkerMinimap" in text
    assert "Show Minimap" in text
    assert "Hide Minimap" in text


def test_collapsed_minimap_uses_compact_aligned_control():
    text = _read("static/style.css")
    assert ".worker-minimap.collapsed" in text
    assert "width: 28px;" in text
    assert "height: 28px;" in text
    assert ".worker-minimap.collapsed .worker-minimap-toggle" in text
    assert "position: static;" in text


def test_minimap_clicks_do_not_start_grid_pointer_interactions():
    text = _read("static/components/BullpenTab.js")
    assert '<div class="worker-minimap" :class="{ collapsed: minimapCollapsed }" @pointerdown.stop>' in text
    assert "@click=\"onMinimapClick\"" in text


def test_minimap_click_navigation_uses_shared_visible_cell_math():
    text = _read("static/components/BullpenTab.js")
    assert "minimapVisibleCells()" in text
    assert "const visible = this.minimapVisibleCells;" in text
    assert "col: col - visible.cols / 2" in text
    assert "row: row - visible.rows / 2" in text
