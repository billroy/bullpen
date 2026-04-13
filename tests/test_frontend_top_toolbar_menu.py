"""Regression checks for top-toolbar main menu import/export wiring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_toolbar_menu_contains_export_import_actions():
    text = _read("static/components/TopToolbar.js")
    assert "@click=\"toggleMainMenu\"" in text
    assert "class=\"project-menu-item\" @click=\"onExportWorkspace\">Export Project</button>" in text
    assert "class=\"project-menu-item\" @click=\"onExportWorkers\">Export Workers</button>" in text
    assert "class=\"project-menu-item\" @click=\"onExportAll\">Export All</button>" in text
    assert "class=\"project-menu-item\" @click=\"triggerImportWorkspace\">Import Project</button>" in text
    assert "class=\"project-menu-item\" @click=\"triggerImportWorkers\">Import Workers</button>" in text
    assert "class=\"project-menu-item\" @click=\"triggerImportAll\">Import All</button>" in text


def test_app_wires_toolbar_export_import_events():
    text = _read("static/app.js")
    assert "@export-workspace=\"exportWorkspace\"" in text
    assert "@export-workers=\"exportWorkers\"" in text
    assert "@export-all=\"exportAll\"" in text
    assert "@import-workspace=\"importWorkspace\"" in text
    assert "@import-workers=\"importWorkers\"" in text
    assert "@import-all=\"importAll\"" in text
    assert "await _downloadZip('/api/export/all', 'bullpen-all.zip');" in text
    assert "await _downloadZip(url, 'bullpen-workers.zip');" in text
    assert "await _importZip('/api/import/all', file, 'All-workspace import complete');" in text
    assert "await _importZip(url, file, 'Workers import complete');" in text


def test_toolbar_menu_css_anchors_from_left_edge():
    text = _read("static/style.css")
    assert ".toolbar-menu {" in text
    assert "left: 0;" in text
    assert "right: auto;" in text
