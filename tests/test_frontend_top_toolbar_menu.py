"""Regression checks for top-toolbar main menu import/export wiring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_toolbar_menu_contains_export_import_actions():
    text = _read("static/components/TopToolbar.js")
    assert "@click=\"toggleMainMenu\"" in text
    assert "class=\"project-menu-item\" @click=\"onExportWorkspace\"><i class=\"menu-item-icon\" data-lucide=\"download\"" in text
    assert "class=\"project-menu-item\" @click=\"onExportWorkers\"><i class=\"menu-item-icon\" data-lucide=\"download\"" in text
    assert "class=\"project-menu-item\" @click=\"onExportAll\"><i class=\"menu-item-icon\" data-lucide=\"download\"" in text
    assert "class=\"project-menu-item\" @click=\"triggerImportWorkspace\"><i class=\"menu-item-icon\" data-lucide=\"upload\"" in text
    assert "class=\"project-menu-item\" @click=\"triggerImportWorkers\"><i class=\"menu-item-icon\" data-lucide=\"upload\"" in text
    assert "class=\"project-menu-item\" @click=\"triggerImportAll\"><i class=\"menu-item-icon\" data-lucide=\"upload\"" in text
    assert "accept=\".bento,application/vnd.bullpen.bento+zip,application/vnd.bento+zip\"" in text
    assert "class=\"project-menu-item\" @click=\"onOpenGitHub\"><i class=\"menu-item-icon\" data-lucide=\"git-branch\"" in text
    assert "class=\"project-menu-item\" @click=\"onLogout\"><i class=\"menu-item-icon\" data-lucide=\"log-out\"" in text
    assert "<span class=\"menu-item-label\">Toggle Left Pane</span></button>" in text
    assert "<span class=\"menu-item-label\">Export Project</span></button>" in text
    assert "<span class=\"menu-item-label\">Export Workers</span></button>" in text
    assert "<span class=\"menu-item-label\">Export All</span></button>" in text
    assert "<span class=\"menu-item-label\">Import Project</span></button>" in text
    assert "<span class=\"menu-item-label\">Import Package</span></button>" in text
    assert "<span class=\"menu-item-label\">Import All</span></button>" in text
    assert "<span class=\"menu-item-label\">Bullpen on GitHub</span></button>" in text
    assert "<span class=\"menu-item-label\">Logout</span></button>" in text
    assert "window.open('https://github.com/billroy/bullpen', '_blank', 'noopener,noreferrer');" in text
    assert "fetch('/login/csrf', { credentials: 'same-origin' });" in text
    assert "form.action = '/logout';" in text
    assert text.index("@click=\"onOpenGitHub\"") < text.index("@click=\"onLogout\"")


def test_toolbar_menu_renders_lucide_icons_after_updates():
    text = _read("static/components/TopToolbar.js")
    assert "mounted() {" in text
    assert "updated() {" in text
    assert "renderLucideIcons(this.$el);" in text
    assert "window.addEventListener('bullpen:menu:close-main', this.onExternalCloseMainMenu);" in text
    assert "window.removeEventListener('bullpen:menu:close-main', this.onExternalCloseMainMenu);" in text
    assert "window.dispatchEvent(new Event('bullpen:menu:close-projects'));" in text
    assert "onExternalCloseMainMenu()" in text


def test_app_wires_toolbar_export_import_events():
    text = _read("static/app.js")
    assert "@export-workspace=\"exportWorkspace\"" in text
    assert "@export-workers=\"exportWorkers\"" in text
    assert "@export-all=\"exportAll\"" in text
    assert "@import-workspace=\"importWorkspace\"" in text
    assert "@import-workers=\"importWorkers\"" in text
    assert "@import-all=\"importAll\"" in text
    assert "await _downloadArchiveExport({ kind: 'all' }, 'bullpen-all.zip');" in text
    assert "await _downloadBentoExport({ kind: 'worker-group', slots }, 'bullpen-workers.bento');" in text
    assert "async function exportWorker(slot) {" in text
    assert "socket.emit('archive:export', _wsData({ ...payload, request_id: requestId }));" in text
    assert "socket.emit('bento:export', _wsData(payload));" in text
    assert "await _downloadBentoExport({ kind: 'worker', slot }, 'bullpen-worker.bento');" in text
    assert "socket.emit('archive:import', _wsData({ ...payload, request_id: requestId }));" in text
    assert "socket.emit('bento:preview', _wsData(payload));" in text
    assert "const preview = await _requestBentoPreview({ file: data });" in text
    assert "const BENTO_RISKY_CAPABILITY_LABELS = {" in text
    assert "commands: 'command fields'" in text
    assert "env: 'environment variables'" in text
    assert "services: 'service worker settings'" in text
    assert "notifications: 'notification settings'" in text
    assert "git: 'git automation settings'" in text
    assert "function _bentoImportApprovalsForPreview(preview)" in text
    assert "window.confirm(" in text
    assert "payload.approvals = approvals;" in text
    assert "Bento import has placement conflicts; placement review is required" in text
    assert "payload.placement = { strategy: 'preserve', state: placement.state };" in text
    assert "return _requestBentoImport(_bentoImportPayloadForPreview(data, preview));" in text
    assert "socket.emit('bento:import', _wsData(payload));" in text
    assert "const data = await file.arrayBuffer();" in text
    assert "const result = await _importArchiveFile(file, 'all');" in text
    assert "Package import complete' + (count ? ` (${count})` : '')" in text
    assert "/api/export/workspace" not in text
    assert "/api/export/all" not in text
    assert "/api/import/workspace" not in text
    assert "/api/import/all" not in text
    assert "/api/export/workers" not in text
    assert "/api/import/workers" not in text


def test_worker_colors_menu_includes_opencode_marker_and_notification():
    text = _read("static/components/TopToolbar.js")
    utils = _read("static/utils.js")
    assert "class=\"provider-colors-title\">Worker colors</div>" in text
    assert "v-for=\"agent in ['antigravity','claude','codex','opencode','shell','service','marker','notification','value']\"" in text
    assert "antigravity: '#0f8b8d'" in utils
    assert "opencode: '#63b3ed'" in utils
    assert "notification: '#d7ad4a'" in utils


def test_toolbar_exposes_worker_pause_and_stop_line_controls():
    text = _read("static/components/TopToolbar.js")
    assert "'pause-automation'," in text
    assert "'resume-automation'," in text
    assert "'stop-the-line'," in text
    assert "'pause-all-automation'," in text
    assert "'resume-all-automation'," in text
    assert "'stop-all-lines'," in text
    assert "toggleSafetyMenu" in text
    assert "Automation safety controls" in text
    assert "toolbar-stop-sign-icon" in text
    assert "safety-menu-status" not in text
    assert "Resume current workspace" in text
    assert "Pause current workspace" in text
    assert "Pause all workspaces..." in text
    assert "Resume all workspaces..." in text
    assert "Stop all workspaces..." in text
    assert "AUTOMATION PAUSED" in text
    assert "window.confirm(" in text


def test_app_wires_toolbar_worker_pause_events():
    text = _read("static/app.js")
    assert ":worker-automation-paused=\"state.config.worker_automation_paused === true\"" in text
    assert "@pause-automation=\"pauseAutomation\"" in text
    assert "@resume-automation=\"resumeAutomation\"" in text
    assert "@stop-the-line=\"stopTheLine\"" in text
    assert "@pause-all-automation=\"pauseAllAutomation\"" in text
    assert "@resume-all-automation=\"resumeAllAutomation\"" in text
    assert "@stop-all-lines=\"stopAllLines\"" in text
    assert "socket.emit('workers:pause_automation'" in text
    assert "socket.emit('workers:resume_automation'" in text
    assert "socket.emit('workers:stop_line'" in text
    assert "socket.emit('workers:pause_all_automation'" in text
    assert "socket.emit('workers:resume_all_automation'" in text
    assert "socket.emit('workers:stop_all_lines'" in text


def test_toolbar_audio_and_worker_color_menus_are_mutually_exclusive():
    text = _read("static/components/TopToolbar.js")
    assert "this.showAudioMenu = false;" in text
    assert "this.showProviderColorsMenu = false;" in text
    assert "toggleProviderColorsMenu()" in text
    assert "toggleAudioMenu()" in text


def test_toolbar_audio_controls_are_consolidated_into_menu():
    text = _read("static/components/TopToolbar.js")
    css = _read("static/style.css")
    assert "toolbar-audio-btn" in text
    assert ":title=\"audioButtonTitle\"" in text
    assert "toolbar-audio-panel" in text
    assert "toolbar-audio-panel-title\">Ambient</div>" in text
    assert "toolbar-audio-panel-title\">Event sounds</div>" in text
    assert "toolbar-audio-label" not in text
    assert "event-sounds-btn" not in text
    assert ".toolbar-audio-btn" in css
    assert ".top-toolbar .toolbar-audio-panel" in css


def test_worker_config_modal_receives_workspace_palette_colors():
    text = _read("static/app.js")
    assert ":provider-colors=\"currentProviderColors\"" in text
    assert ":default-provider-colors=\"defaultProviderColors\"" in text


def test_toolbar_menu_css_anchors_from_left_edge():
    text = _read("static/style.css")
    assert ".toolbar-menu {" in text
    assert "left: 0;" in text
    assert "right: auto;" in text
