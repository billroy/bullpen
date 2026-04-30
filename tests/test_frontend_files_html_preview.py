"""Regression checks for safe HTML preview handling in FilesTab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_files_tab_does_not_open_html_in_new_same_origin_window():
    text = _read("static/components/FilesTab.js")
    assert "window.open(this._filesUrl(node.path)" not in text
    assert "<iframe v-if=\"viewMode === 'preview'\" sandbox :srcdoc=\"activeFile.content\" class=\"html-iframe\"></iframe>" in text


def test_files_tab_detail_viewer_has_download_button_next_to_edit():
    text = _read("static/components/FilesTab.js")
    assert "<button v-if=\"canEdit\" class=\"btn btn-sm\" @click=\"startEditing\">Edit</button>" in text
    assert "class=\"btn btn-sm file-download-button\" :href=\"downloadUrl\" :download=\"activeFile.name\"" in text
    assert "return this._filesUrl(this.activeFile.path, { raw: '1' });" in text
