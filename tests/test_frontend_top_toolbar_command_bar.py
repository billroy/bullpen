"""Regression checks for top-toolbar command palette behavior."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_top_toolbar_routes_gt_prefixed_entries_to_palette_events():
    text = _read("static/components/TopToolbar.js")
    assert "'run-palette-command'," in text
    assert "'run-palette-input'," in text
    assert "if (this.paletteMode === 'command') {" in text
    assert "this.$emit('run-palette-command', result.command.id, result.args || '');" in text
    assert "this.$emit('run-palette-input', text);" in text
    assert "this.quickCreateText = '';" in text
    assert "this.$emit('quick-create-task', this.quickCreatePayload(payload));" in text
    assert "text.startsWith('>')" in text
    assert "text.startsWith('?')" in text
    assert "text.startsWith('/')" not in text


def test_app_wires_top_toolbar_palette_events_to_registry_handlers():
    text = _read("static/app.js")
    assert ":palette-commands=\"paletteCommands\"" in text
    assert "@run-palette-command=\"runPaletteCommand\"" in text
    assert "@run-palette-input=\"runPaletteInput\"" in text
    assert "const paletteCommands = computed(() => {" in text
    assert "function runPaletteCommand(commandId, args = '') {" in text
    assert "function runPaletteInput(input) {" in text
    assert "function runCommandBar(input) {" not in text
    assert "Disconnected from Bullpen server. Ticket was not created." in text


def test_command_registry_supports_ticket_and_ui_commands():
    text = _read("static/commands.js")
    assert "id: 'ticket.create'" in text
    assert "id: 'tab.open'" in text
    assert "id: 'tickets.view'" in text
    assert "id: 'tickets.scope'" in text
    assert "id: 'theme.change'" in text
    assert "id: 'ambient.change'" in text
    assert "id: 'volume.set'" in text
    assert "id: 'chat.new'" in text
    assert "title: 'Export This Project'" in text
    assert "title: 'Export Workers'" in text
    assert "title: 'Export All Projects'" in text
    assert "id: 'project.import'" in text
    assert "id: 'packages.import'" not in text
    assert "id: 'project.import_all'" not in text
    assert "title: 'Import...'" in text
    assert "aliases: ['import', 'import project', 'import workspace', 'import package', 'import workers', 'import bento', 'import all']" in text
    assert "run: runCtx => runCtx.actions.importAnyFromPicker()" in text
    assert "Usage: >view kanban|list" in text
    assert "Usage: >scope live|archived" in text
    assert "Usage: >volume 0-100" in text


def test_command_registry_is_loaded_before_components():
    text = _read("static/index.html")
    assert '<script src="/commands.js"></script>' in text
    assert text.index('<script src="/commands.js"></script>') < text.index('<script src="/components/TopToolbar.js"></script>')


def test_toolbar_teaches_ticket_body_and_gt_command_mode():
    text = _read("static/components/TopToolbar.js")
    assert 'placeholder="New ticket / description, or > commands"' in text
    assert "Use Title / description" in text
    assert "Type > to run Bullpen commands" in text
    assert "Create ticket:" in text


def test_toolbar_quick_create_column_selector_is_local_and_writable():
    toolbar = _read("static/components/TopToolbar.js")
    app = _read("static/app.js")
    css = _read("static/style.css")

    assert "'projectName', 'projectPath', 'activeWorkspaceId'" in toolbar
    assert "'paletteCommands', 'columns']" in toolbar
    assert "const workerColumns = new Set(['assigned', 'in_progress']);" in toolbar
    assert ".filter(col => col?.key && !workerColumns.has(col.key))" in toolbar
    assert "return columns.length ? columns : [{ key: 'inbox', label: 'Inbox' }];" in toolbar
    assert "if (this.writableColumns.some(col => col.key === 'inbox')) return 'inbox';" in toolbar
    assert "quickCreateStatusStorageKey()" in toolbar
    assert "const workspaceKey = String(this.activeWorkspaceId || this.projectPath || 'default');" in toolbar
    assert "return `bullpen.quickCreate.status.${workspaceKey}`;" in toolbar
    assert "window.localStorage?.getItem(this.quickCreateStatusStorageKey())" in toolbar
    assert "window.localStorage?.setItem(this.quickCreateStatusStorageKey(), this.quickCreateStatus || this.defaultQuickCreateStatus);" in toolbar
    assert "window.localStorage?.getItem('bullpen.quickCreate.status')" not in toolbar
    assert "activeWorkspaceId() {" in toolbar
    assert '<select\n                class="form-select toolbar-quick-create-status"' in toolbar
    assert toolbar.index('class="quick-create-input toolbar-quick-create-input"') < toolbar.index('class="form-select toolbar-quick-create-status"')
    assert '<option v-for="col in writableColumns" :key="col.key" :value="col.key">{{ col.label }}</option>' in toolbar
    assert "return { ...payload, status: this.quickCreateStatus };" in toolbar
    assert ':active-workspace-id="activeWorkspaceId"' in app
    assert ':columns="state.config.columns"' in app
    assert ".toolbar-quick-create-row" in css
    assert ".top-toolbar .toolbar-quick-create-status" in css


def test_empty_toolbar_focus_does_not_open_inline_palette_until_input():
    text = _read("static/components/TopToolbar.js")
    assert "if (!this.quickCreateText.trim() && !this.paletteOverlayOpen) return;" in text
    assert "onPaletteInput()" in text
    assert '@input="onPaletteInput"' in text


def test_inline_palette_closes_when_browser_window_loses_focus():
    text = _read("static/components/TopToolbar.js")
    assert "window.addEventListener('blur', this.onWindowBlur);" in text
    assert "window.removeEventListener('blur', this.onWindowBlur);" in text
    assert "onWindowBlur()" in text
    assert "if (!this.paletteOverlayOpen) this.showPalette = false;" in text
