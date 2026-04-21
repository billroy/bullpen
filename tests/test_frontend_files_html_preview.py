"""Regression checks for safe HTML preview handling in FilesTab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_files_tab_does_not_open_html_in_new_same_origin_window():
    text = _read("static/components/FilesTab.js")
    assert "window.open(this._filesUrl(node.path)" not in text
    assert "<iframe v-if=\"viewMode === 'preview'\" sandbox :srcdoc=\"activeFile.content\" class=\"html-iframe\"></iframe>" in text
