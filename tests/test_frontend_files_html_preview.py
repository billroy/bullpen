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
    assert "class=\"btn btn-sm file-download-button\" @click=\"downloadActiveFile\"" in text
    assert "URL.createObjectURL(blob)" in text
    assert "_filesUrl(" not in text


def test_files_tab_detail_viewer_has_browser_open_button():
    text = _read("static/components/FilesTab.js")
    app = _read("static/app.js")
    css = _read("static/style.css")
    assert "const BROWSER_OPENABLE_EXTENSIONS = new Set([" in text
    assert "'.html', '.htm', '.pdf'" in text
    assert "const BINARY_PREVIEW_EXTENSIONS = new Set([" in text
    assert "BINARY_PREVIEW_EXTENSIONS.has(ext)" in text
    assert "canOpenInBrowser()" in text
    assert "class=\"btn btn-sm file-open-browser-button\" @click=\"openActiveFileInBrowser\"" in text
    assert "data-lucide=\"external-link\"" in text
    assert "v-else-if=\"isAudio\" class=\"file-view-audio\"" in text
    assert "v-else-if=\"isVideo\" class=\"file-view-video\"" in text
    assert "this.$root.requestFileOpenExternal({ workspaceId: this.workspaceId, path: this.activeFile.path })" in text
    assert "function requestFileOpenExternal(payload = {})" in app
    assert "requestEvent: 'files:open_external'" in app
    assert "successEvent: 'files:opened_external'" in app
    assert ".file-open-browser-button" in css


def test_files_tab_has_distinct_loaded_empty_and_error_states():
    text = _read("static/components/FilesTab.js")
    assert 'v-if="loadingTree"' in text
    assert 'v-else-if="treeError"' in text
    assert '<div v-else class="empty-state">No files found</div>' in text
    assert "this.treeError = 'Could not load files';" in text


def test_files_tab_uses_socket_events_for_app_file_operations():
    text = _read("static/components/FilesTab.js")
    app = _read("static/app.js")
    assert "this.$root.requestFileTree({ workspaceId: this.workspaceId })" in text
    assert "this.$root.requestFileRead({ workspaceId: this.workspaceId, path: node.path })" in text
    assert "this.$root.requestFileBinary({ workspaceId: this.workspaceId, path: file.path })" in text
    assert "this.$root.requestFileWrite({" in text
    assert "this.$root.requestFileExists({ workspaceId: this.workspaceId, path })" in text
    assert "filesFetch(" not in text
    assert "function requestFileTree(payload = {})" in app
    assert "function requestFileBinary(payload = {})" in app
    assert "requestEvent: 'files:binary'" in app
    assert "socket.emit(requestEvent, _wsData({ ...payload, request_id: requestId }));" in app
