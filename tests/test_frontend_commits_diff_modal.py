"""Regression checks for commit diff modal behavior in commits tab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_commits_tab_rows_open_diff_modal():
    text = _read("static/components/CommitsTab.js")
    app = _read("static/app.js")
    assert "@click=\"openDiff(commit)\"" in text
    assert "class=\"modal-overlay commits-diff-overlay\"" in text
    assert "@keydown.escape=\"closeDiff\"" in text
    assert "this.$root.requestCommitDiff({" in text
    assert "function requestCommitDiff(payload = {})" in app
    assert "socket.emit('commits:diff', _wsData({ ...payload, request_id: requestId }));" in app
    assert "/api/commits" not in text


def test_commits_tab_requests_are_workspace_scoped():
    text = _read("static/components/CommitsTab.js")
    app = _read("static/app.js")
    assert "props: ['workspaceId', 'openDiffHash']" in text
    assert "emits: ['handled-open-diff-hash']" in text
    assert "this.$root.requestCommits({" in text
    assert "workspaceId: this.workspaceId" in text
    assert "function requestCommits(payload = {})" in app
    assert "socket.emit('commits:list', _wsData({ ...payload, request_id: requestId }));" in app
    assert "workspaceId(newId, oldId)" in text
    assert "openDiffHash:" in text
    assert "this.openDiffByHash(newHash);" in text


def test_commits_tab_receives_active_workspace_id():
    text = _read("static/app.js")
    assert ":workspace-id=\"activeWorkspaceId\"" in text
    assert ":open-diff-hash=\"requestedCommitDiffHash\"" in text
    assert "@handled-open-diff-hash=\"requestedCommitDiffHash = ''\"" in text
    assert ":key=\"'commits-' + (activeWorkspaceId || 'none')\"" in text


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


def test_commits_tab_refresh_auto_loads_all_todays_commits():
    text = _read("static/components/CommitsTab.js")
    assert "await this.loadUntilOlderThanToday();" in text
    assert "async loadUntilOlderThanToday()" in text
    assert "while (this.hasMore && this._lastLoadedCommitIsToday())" in text
    assert "if (!loaded) break;" in text
    assert "_isTodayCommit(commit)" in text
