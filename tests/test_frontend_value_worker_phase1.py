"""Source-level checks for initial value worker frontend wiring."""

import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_value_worker_type_metadata_is_registered():
    text = (ROOT / "static" / "utils.js").read_text()

    assert "value: '#166534'" in text
    assert "worker?.type === 'value'" in text
    assert "'value', 'eval'" in text
    assert "function isValueWorker(worker)" in text
    assert "return 'equal';" in text
    assert "return 'Value';" in text


def test_grid_geometry_exposes_cell_reference_helpers_used_by_bullpen_tab():
    geometry = (ROOT / "static" / "gridGeometry.js").read_text()
    tab = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert "function parseCellRef(text)" in geometry
    assert "function colLabel(col)" in geometry
    assert "function rowLabel(row)" in geometry
    assert "function coordToCellRef(coord)" in geometry
    assert "parseCellRef," in geometry
    assert "coordToCellRef," in geometry
    assert "return GridGeometry.parseCellRef(text);" in tab
    assert "return GridGeometry.colLabel(col);" in tab
    assert "return GridGeometry.rowLabel(row);" in tab


def test_value_worker_can_be_created_from_library():
    text = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert "libraryMode === 'value'" in text
    assert 'data-lucide="equal"' in text
    assert "Blank value worker" in text
    assert "addValueWorker()" in text
    assert "type: 'value'" in text
    assert "value_type: 'auto'" in text
    assert "save_history: false" in text


def test_value_worker_config_modal_has_value_fields_only():
    text = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text()

    assert "isValue()" in text
    assert '<span v-if="isValue" class="worker-type-badge">Value</span>' in text
    assert '<template v-if="isValue">' in text
    assert 'v-model="form.value"' in text
    assert 'v-model="form.value_type"' in text
    assert 'v-model="form.format.kind"' in text
    assert 'v-model="form.save_history"' in text
    assert "fields.save_history = !!fields.save_history;" in text
    assert 'v-if="!isService && !isValue"' in text
    value_save_branch = text.split("if (this.isValue) {", 1)[1].split("} else if (this.isMarker || this.isNotification) {", 1)[0]
    assert "delete fields.activation;" in value_save_branch
    assert "delete fields.disposition;" in value_save_branch
    assert "delete fields.notification;" in value_save_branch


def test_value_worker_card_displays_value_without_run_controls():
    text = (ROOT / "static" / "components" / "WorkerCard.js").read_text()

    assert 'v-else-if="isValue" class="worker-card-value"' in text
    assert "{{ valueCellRef || 'Value' }}" in text
    assert "{{ valueDisplay || 'Empty' }}" in text
    assert "return isValueWorker(this.worker);" in text
    assert "if (this.isValue) return false;" in text
    assert "return !this.isMarker && !this.isValue && !this.isEval && !this.isUnknownType;" in text
    assert "window.GridGeometry?.coordToCellRef?.(this.worker)" in text
    assert "if (this.isValue) return false;" in text


def test_value_worker_small_card_shows_value_in_header():
    card = (ROOT / "static" / "components" / "WorkerCard.js").read_text()
    css = (ROOT / "static" / "style.css").read_text()

    assert 'v-if="showCompactValue && valueEditing"' in card
    assert 'v-if="showCompactValue && !valueEditing"' in card
    assert 'class="worker-card-compact-value worker-card-compact-value-button"' in card
    assert 'class="worker-card-compact-value-editor"' in card
    assert 'class="worker-card-compact-value-editor worker-card-value-input"' not in card
    assert '@click.stop="startCompactValueEdit"' in card
    assert '@dblclick.stop' in card
    assert "valueInlineDisplay()" not in card
    assert "{{ valueInlineDisplay }}" not in card
    assert "parseValueEditText(text)" in card
    assert "return this.isValue && this.effectiveLayoutMode === 'small';" in card
    assert "{{ workerNameWithPort }}" in card
    assert "{{ valueDisplay || 'Empty' }}" in card
    assert "`${String(this.worker?.name || '').trim()}:${this.storedValueText}`" in card
    assert ".worker-card-compact-value {" in css
    assert ".worker-card-compact-value-button {" in css
    assert ".worker-card-compact-value-editor {" in css
    assert "text-overflow: ellipsis;" in css
    compact_button_styles = css.split(".worker-card-compact-value-button {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 auto;" not in compact_button_styles
    assert "max-width: none;" not in compact_button_styles
    compact_editor_styles = css.split(".worker-card-compact-value-editor {", 1)[1].split("}", 1)[0]
    assert "align-self: stretch;" in compact_editor_styles
    assert "box-sizing: border-box;" in compact_editor_styles
    assert "padding: 0 8px;" in compact_editor_styles


def test_value_worker_card_rejects_ticket_drop_affordances():
    card = (ROOT / "static" / "components" / "WorkerCard.js").read_text()
    roster = (ROOT / "static" / "components" / "LeftPane.js").read_text()

    assert ':aria-label="cardAriaLabel"' in card
    assert "Not a ticket drop target." in card
    assert "acceptsTaskDrop()" in card
    assert "return !this.isValue && !this.isDisabledType;" in card
    assert "isTaskDrag && !this.acceptsTaskDrop" in card
    assert "taskId && this.acceptsTaskDrop" in card
    assert "rosterWorkerAcceptsTaskDrop(worker)" in roster
    assert "return !['value', 'eval'].includes(type);" in roster


def test_value_worker_card_styles_exist():
    text = (ROOT / "static" / "style.css").read_text()

    assert ".worker-card-value {" in text
    assert ".worker-card-value-meta {" in text
    assert ".worker-card-value-main {" in text


def test_numeric_value_worker_card_has_sparkline_and_graph_modal():
    card = (ROOT / "static" / "components" / "WorkerCard.js").read_text()
    css = (ROOT / "static" / "style.css").read_text()

    assert 'v-if="hasNumericValueSparkline"' in card
    assert 'class="worker-card-value-sparkline-button"' in card
    assert '@click.stop="openValueGraph"' in card
    assert "numericValueHistory()" in card
    assert "valueGraphOpen" in card
    assert 'class="modal value-graph-modal"' in card
    assert 'v-if="valueHistoryEnabled"' in card
    assert "Show History" in card
    assert "menuShowValueHistory()" in card
    assert "valueHistoryRows()" in card
    assert "if (!this.valueHistoryEnabled) return [];" in card
    assert "exportValueHistoryCsv()" in card
    assert 'class="value-history-table"' in card
    assert 'a.download = `${this.valueHistoryFilenameBase()}.csv`;' in card
    assert "buildChartPoints(points, width, height, inset)" in card
    assert ".worker-card-value-sparkline-button {" in css
    assert ".value-graph-modal {" in css
    assert ".value-graph-chart {" in css
    assert ".value-history-pane {" in css
    assert ".value-history-table {" in css


def test_value_shortcut_editor_parses_and_creates_values():
    text = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert "valueShortcutEditor: null" in text
    assert "printableValueShortcutKey(e)" in text
    assert "parseValueShortcutText(text)" in text
    assert "const colon = raw.indexOf(':');" in text
    assert "this.$emit('add-worker', {" in text
    assert "type: 'value'," in text
    assert "this.commitValueShortcutEditor({ openModal: e.metaKey || e.ctrlKey });" in text
    assert "this.createWorkerAndOpenConfig({ type: 'value', fields: parsed.fields });" in text
    assert "if (e.defaultPrevented) return;" in text


def test_value_shortcut_parser_handles_label_less_colon_values():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "components" / "BullpenTab.js"))}, 'utf8');
const context = {{
  console,
  localStorage: {{ getItem: () => null, setItem: () => {{}} }},
  WorkerCard: {{}},
}};
vm.createContext(context);
vm.runInContext(source + `
  globalThis.__parsed = {{
    labelLessNumber: BullpenTab.methods.parseValueShortcutText(':40'),
    labelLessText: BullpenTab.methods.parseValueShortcutText(':foo'),
    named: BullpenTab.methods.parseValueShortcutText('tax rate: 5.5'),
    plain: BullpenTab.methods.parseValueShortcutText('foo'),
    emptyAfterColon: BullpenTab.methods.parseValueShortcutText('name:'),
  }};
`, context);
process.stdout.write(JSON.stringify(context.__parsed));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)

    assert parsed["labelLessNumber"]["fields"]["name"] == ""
    assert parsed["labelLessNumber"]["fields"]["value"] == "40"
    assert parsed["labelLessText"]["fields"]["name"] == ""
    assert parsed["labelLessText"]["fields"]["value"] == "foo"
    assert parsed["named"]["fields"]["name"] == "tax rate"
    assert parsed["named"]["fields"]["value"] == "5.5"
    assert parsed["plain"]["fields"]["name"] == ""
    assert parsed["plain"]["fields"]["value"] == "foo"
    assert parsed["emptyAfterColon"]["error"] == "Enter a value."


def test_worksheet_clipboard_parser_handles_tabular_values():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "components" / "BullpenTab.js"))}, 'utf8');
const context = {{
  console,
  localStorage: {{ getItem: () => null, setItem: () => {{}} }},
  WorkerCard: {{}},
  plainText: {json.dumps("a\tb\r\nc\td\r\n")},
  quotedText: {json.dumps('"a\t1"\t"b ""two"""\n3\t4')},
  singleText: {json.dumps("not worksheet data")},
  raggedText: {json.dumps("a\tb\nc")},
}};
vm.createContext(context);
vm.runInContext(source + `
  const parse = BullpenTab.methods.parseWorksheetClipboardText;
  globalThis.__parsed = {{
    plain: parse(plainText),
    quoted: parse(quotedText),
    singleText: parse(singleText),
    ragged: parse(raggedText),
  }};
`, context);
process.stdout.write(JSON.stringify(context.__parsed));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)

    assert parsed["plain"] == [["a", "b"], ["c", "d"]]
    assert parsed["quoted"] == [["a\t1", 'b "two"'], ["3", "4"]]
    assert parsed["singleText"] is None
    assert parsed["ragged"] == [["a", "b"], ["c", ""]]


def test_worksheet_paste_builds_unlabeled_value_workers_and_rejects_conflicts():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "components" / "BullpenTab.js"))}, 'utf8');
const calls = [];
const toasts = [];
const context = {{
  console,
  localStorage: {{ getItem: () => null, setItem: () => {{}} }},
  WorkerCard: {{}},
  GridGeometry: {{ coordKey: (col, row) => `${{col}},${{row}}` }},
  pasteText: {json.dumps("1\t2\n3\t4\n")},
  conflictText: {json.dumps("a\tb\n")},
}};
vm.createContext(context);
vm.runInContext(source + `
  const methods = BullpenTab.methods;
  const component = {{
    $root: {{
      pasteWorkerGroup(items) {{ globalThis.__calls.push(items); }},
      addToast(message, type) {{ globalThis.__toasts.push({{ message, type }}); }},
    }},
    emptyMenuCoord: {{ col: 2, row: 3 }},
    liveMessage: '',
    parseWorksheetClipboardText: methods.parseWorksheetClipboardText,
    worksheetPasteTargetsForCoord: methods.worksheetPasteTargetsForCoord,
    validateWorksheetPasteTargets: methods.validateWorksheetPasteTargets,
    showPasteError: methods.showPasteError,
    itemAtCoord(coord) {{ return coord.col === 3 && coord.row === 2 ? {{ slotIndex: 8 }} : null; }},
    isWritableCoord(coord) {{ return coord && coord.col >= 0 && coord.row >= 0 && coord.col <= 100 && coord.row <= 100; }},
  }};
  globalThis.__calls = [];
  globalThis.__toasts = [];
  const pasted = methods.pasteWorksheetCells.call(component, {{ col: 4, row: 6 }}, pasteText);
  const rejected = methods.pasteWorksheetCells.call(component, {{ col: 2, row: 2 }}, conflictText);
  globalThis.__result = {{ pasted, rejected, calls: globalThis.__calls, toasts: globalThis.__toasts, liveMessage: component.liveMessage, emptyMenuCoord: component.emptyMenuCoord }};
`, context);
process.stdout.write(JSON.stringify(context.__result));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["pasted"] is True
    assert payload["rejected"] is False
    assert payload["emptyMenuCoord"] is None
    assert len(payload["calls"]) == 1
    assert [item["coord"] for item in payload["calls"][0]] == [
        {"col": 4, "row": 6},
        {"col": 5, "row": 6},
        {"col": 4, "row": 7},
        {"col": 5, "row": 7},
    ]
    assert all(item["worker"]["type"] == "value" for item in payload["calls"][0])
    assert all(item["worker"]["name"] == "" for item in payload["calls"][0])
    assert [item["worker"]["value"] for item in payload["calls"][0]] == ["1", "2", "3", "4"]
    assert payload["toasts"] == [{"message": "Worksheet paste would overwrite an occupied cell", "type": "error"}]
    assert payload["liveMessage"] == "Worksheet paste would overwrite an occupied cell"


def test_worker_grid_ctrl_v_uses_system_clipboard_for_worksheet_paste():
    text = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert "this.pasteFromClipboard(this.selectedCell);" in text
    assert "navigator.clipboard?.readText" in text
    assert "this.pasteWorksheetCells(coord, clipboardText);" in text
    assert "this.pasteWorker(coord, { allowReplaceSingle: true });" in text
    assert "Worksheet paste would overwrite an occupied cell" in text
    assert "this.$root.addToast(message, 'error');" in text


def test_value_card_inline_edit_saves_and_reverts():
    text = (ROOT / "static" / "components" / "WorkerCard.js").read_text()

    assert "valueEditing: false" in text
    assert "valueEditIncludesName: false" in text
    assert '@keydown.enter.prevent.stop="commitValueEdit"' in text
    assert '@keydown.escape.prevent.stop="cancelValueEdit"' in text
    assert text.count('@blur="cancelValueEdit"') >= 2
    assert "this._closeValueEdit = (e) => {" in text
    assert "document.addEventListener('pointerdown', this._closeValueEdit, true);" in text
    assert "document.removeEventListener('pointerdown', this._closeValueEdit, true);" in text
    assert "@click.stop=\"startValueEdit\"" in text
    assert "startCompactValueEdit()" in text
    assert "validateValueEditText(text)" in text
    assert "Enter a valid number." in text
    assert "fields: this.valueEditIncludesName" in text
    assert "? { name: parsed.name, value: parsed.value }" in text
    assert ": { value: parsed.value }" in text
    assert "this.cancelValueEdit();" in text


def test_value_card_compact_editor_saves_name_and_value_only():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "components" / "WorkerCard.js"))}, 'utf8');
const calls = [];
const context = {{
  console,
  isValueWorker: worker => worker?.type === 'value',
  renderLucideIcons: () => {{}},
}};
vm.createContext(context);
vm.runInContext(source + `
  const methods = WorkerCard.methods;
  const component = {{
    worker: {{ type: 'value', name: 'interest rate', value_type: 'auto' }},
    valueEditIncludesName: true,
    valueEditText: 'tax rate:6.4%',
    slotIndex: 7,
    parseValueEditText: methods.parseValueEditText,
    validateValueEditText: methods.validateValueEditText,
    cancelValueEdit() {{ this.cancelled = true; }},
    $root: {{ saveWorkerConfig(payload) {{ globalThis.__calls.push(payload); }} }},
  }};
  globalThis.__calls = [];
  methods.commitValueEdit.call(component);
  globalThis.__result = {{ calls: globalThis.__calls, cancelled: component.cancelled }};
`, context);
process.stdout.write(JSON.stringify(context.__result));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["calls"] == [{
        "slot": 7,
        "fields": {"name": "tax rate", "value": "6.4%"},
    }]
    assert payload["cancelled"] is True
