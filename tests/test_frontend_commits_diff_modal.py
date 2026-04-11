"""Regression checks for commit diff modal behavior in commits tab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_commits_tab_rows_open_diff_modal():
    text = _read("static/components/CommitsTab.js")
    assert "@click=\"openDiff(commit)\"" in text
    assert "class=\"modal-overlay commits-diff-overlay\"" in text
    assert "@keydown.escape=\"closeDiff\"" in text
    assert "fetch(`/api/commits/${encodeURIComponent(commit.hash)}/diff`)" in text
