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


def test_commits_diff_is_colorized_with_line_classes():
    text = _read("static/components/CommitsTab.js")
    assert "v-html=\"highlightedDiffHtml\"" in text
    assert "classifyDiffLine(line)" in text
    assert "commit-diff-line-add" in text
    assert "commit-diff-line-remove" in text
    assert "commit-diff-line-hunk" in text


def test_commits_diff_line_styles_exist_for_dark_and_light_modes():
    text = _read("static/style.css")
    assert ".commit-diff-line-add" in text
    assert ".commit-diff-line-remove" in text
    assert ".commit-diff-line-hunk" in text
    assert "[data-theme=\"light\"] .commit-diff-line-add" in text
    assert "[data-theme=\"light\"] .commit-diff-line-remove" in text
