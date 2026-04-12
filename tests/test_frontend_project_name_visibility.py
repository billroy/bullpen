"""Regression checks for workspace project name visibility in title/header."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_app_title_uses_workspace_base_name():
    text = _read("static/app.js")
    assert "function _workspaceBaseName(workspacePath)" in text
    assert "trimmed.split(/[\\\\/]+/).filter(Boolean);" in text
    assert "document.title = project ? `Bullpen : ${project}` : 'Bullpen';" in text


def test_top_toolbar_renders_bullpen_with_project_suffix():
    text = _read("static/components/TopToolbar.js")
    assert "props: ['projectName', 'connected', 'themes', 'activeTheme', 'ambientPresets', 'ambientPreset', 'ambientVolume']" in text
    assert "Bullpen<span v-if=\"projectName\"> / {{ projectName }}</span>" in text
