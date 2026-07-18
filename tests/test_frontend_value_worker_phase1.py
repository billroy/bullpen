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
    assert "function getValueWorkerVisualKind(worker)" in text
    assert "return kind === 'number' ? 'hash' : 'type';" in text
    assert "if (kind === 'formula') return 'Formula';" in text


def test_value_worker_icon_triplet_uses_formula_numeric_and_text_semantics():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "utils.js"))}, 'utf8');
const context = {{ window: {{}}, URL, console }};
vm.createContext(context);
vm.runInContext(source + `
  const workers = {{
    formulaNumber: {{ type: 'value', value: 4, resolved_value_type: 'number', formula: {{ source: '=2+2' }} }},
    formulaText: {{ type: 'value', value: 'ok', resolved_value_type: 'string', formula: {{ source: '=\"ok\"' }} }},
    numeric: {{ type: 'value', value: 42, value_type: 'auto', resolved_value_type: 'number' }},
    text: {{ type: 'value', value: '42', value_type: 'string', resolved_value_type: 'string' }},
    empty: {{ type: 'value', value: null, value_type: 'auto', resolved_value_type: 'null' }},
  }};
  globalThis.__result = Object.fromEntries(Object.entries(workers).map(([key, worker]) => [key, {{
    kind: getValueWorkerVisualKind(worker),
    icon: getWorkerTypeIcon(worker),
    label: workerTypeLabel(worker),
  }}]));
`, context);
process.stdout.write(JSON.stringify(context.__result));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["formulaNumber"] == {"kind": "formula", "icon": "", "label": "Formula"}
    assert payload["formulaText"] == {"kind": "formula", "icon": "", "label": "Formula"}
    assert payload["numeric"] == {"kind": "number", "icon": "hash", "label": "Numeric value"}
    assert payload["text"] == {"kind": "text", "icon": "type", "label": "Text value"}
    assert payload["empty"] == {"kind": "text", "icon": "type", "label": "Text value"}


def test_value_icon_triplet_is_rendered_on_cards_and_roster_with_accessible_labels():
    card = (ROOT / "static" / "components" / "WorkerCard.js").read_text()
    roster = (ROOT / "static" / "components" / "LeftPane.js").read_text()
    style = (ROOT / "static" / "style.css").read_text()

    assert "valueVisualKind === 'formula'" in card
    assert "value-kind-glyph value-kind-glyph--card" in card
    assert ':aria-label="workerTypeLabel"' in card
    assert "valueWorkerVisualKind(w) === 'formula'" in roster
    assert "value-kind-glyph value-kind-glyph--roster" in roster
    assert ':aria-label="workerTypeVisualLabel(w)"' in roster
    assert "resolved_value_type: s.resolved_value_type" in roster
    assert "formula: s.formula" in roster
    assert ".value-kind-glyph--card" in style
    assert ".value-kind-glyph--roster" in style


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
    assert "unit: ''" in text
    assert "save_history: true" in text


def test_value_worker_config_modal_has_value_fields_only():
    text = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text()

    assert "isValue()" in text
    assert '<span v-if="isValue" class="worker-type-badge">Value</span>' in text
    assert '<template v-if="isValue">' in text
    assert 'v-model="form.value"' in text
    assert 'v-model="form.value_type"' in text
    assert 'v-model="valueUnitMode"' in text
    assert 'v-model="form.unit"' in text
    assert 'v-model="form.format.kind"' in text
    assert '<option value="general">General</option>' in text
    assert 'Auto (by value type)' not in text
    assert '@change="onValueFormatKindChange"' in text
    assert 'v-model="form.format.places"' in text
    assert 'v-model="form.format.grouping"' in text
    assert "format.places = null" in text
    assert "format.grouping = true" in text
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
    value_card = text.split('v-else-if="isValue" class="worker-card-value"', 1)[1].split('v-else-if="isNotification"', 1)[0]
    assert "worker-card-value-meta" not in value_card
    assert "{{ valueCellRef || 'Value' }}" not in value_card
    assert "{{ valueTypeLabel }}" not in value_card
    assert "{{ valueDisplay || 'Empty' }}" in text
    assert "return isValueWorker(this.worker);" in text
    assert "if (this.isValue) return false;" in text
    assert "return !this.isMarker && !this.isValue && !this.isEval && !this.isUnknownType;" in text
    assert "window.GridGeometry?.coordToCellRef?.(this.worker)" in text
    assert "this.worker?.name || (this.isValue && this.shouldShowValueCellRef ? this.valueCellRef : '')" in text
    assert "shouldShowValueCellRef()" in text
    assert "this.isCardHovered || this.isSelected" in text
    assert "@mouseenter=\"onCardMouseEnter\"" in text
    assert "this.isCardHovered = false;" in text
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
    assert "const unit = String(this.worker?.unit || '').trim();" in card
    assert "const source = this.worker?.formula?.source || this.storedValueText;" in card
    assert "const label = unit ? `${name}/${unit}` : name;" in card
    assert "return label ? `${label}:${source}` : source;" in card
    assert ".worker-card-compact-value {" in css
    assert ".worker-card-compact-value-button {" in css
    assert "'worker-card-compact-value--wide': !spreadsheetHasLabel" in card
    wide_value_styles = css.split(".worker-card-compact-value--wide {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 auto;" in wide_value_styles
    assert "max-width: none;" in wide_value_styles
    assert "'worker-card-identity--cell-ref': isValue && !spreadsheetHasLabel" in card
    cell_ref_styles = css.split(".worker-card--small .worker-card-identity--cell-ref {", 1)[1].split("}", 1)[0]
    assert "flex: 0 1 auto;" in cell_ref_styles
    assert ".worker-card-compact-value-editor {" in css
    assert "text-overflow: ellipsis;" in css
    compact_button_styles = css.split(".worker-card-compact-value-button {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 auto;" not in compact_button_styles
    assert "max-width: none;" not in compact_button_styles
    compact_editor_styles = css.split(".worker-card-compact-value-editor {", 1)[1].split("}", 1)[0]
    assert "align-self: stretch;" in compact_editor_styles
    assert "box-sizing: border-box;" in compact_editor_styles
    assert "padding: 0 8px;" in compact_editor_styles


def test_compact_worker_spreadsheet_style_restores_pill_when_selected():
    card = (ROOT / "static" / "components" / "WorkerCard.js").read_text()
    grid = (ROOT / "static" / "components" / "BullpenTab.js").read_text()
    css = (ROOT / "static" / "style.css").read_text()

    assert "'worker-card--spreadsheet': usesSpreadsheetStyle" in card
    assert "this.useCompactPill === false" in card
    assert "&& !this.isSelected" in card
    assert "&& !this.valueEditing" in card
    assert 'v-if="!usesSpreadsheetStyle"' in card
    assert ":use-compact-pill=\"workerUsesCompactPill(item.worker)\"" in grid
    assert "return this.config?.worker_pill_styles?.[key] !== false;" in grid
    assert ".worker-card.worker-card--small.worker-card--spreadsheet" in css
    assert ".worker-card--spreadsheet .worker-card-compact-value--left" in css
    assert ".worker-card--spreadsheet .worker-card-compact-value--right" in css


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
    assert ".worker-card-value-meta {" not in text
    assert ".worker-card-value-main {" in text


def test_value_worker_card_formats_grouping_and_decimal_modes():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "components" / "WorkerCard.js"))}, 'utf8');
const context = {{ console, WorkerCard: undefined, window: {{}}, document: {{}}, URL: {{}} }};
vm.createContext(context);
vm.runInContext(source + `
  const display = WorkerCard.computed.valueDisplayBase;
  const render = (format, value = 12000.5, resolved = 'number') =>
    display.call({{ worker: {{ value, resolved_value_type: resolved, format }} }});
  globalThis.__result = {{
    automatic: render({{ kind: 'number', places: null, grouping: true }}),
    fixed: render({{ kind: 'number', places: 2, grouping: true }}),
    ungrouped: render({{ kind: 'number', places: null, grouping: false }}),
    stringValue: render({{ kind: 'number', places: 2, grouping: true }}, '12000', 'string'),
    negativeZero: render({{ kind: 'number', places: 2, grouping: true }}, -0.004, 'number'),
  }};
`, context);
process.stdout.write(JSON.stringify(context.__result));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "automatic": "12,000.5",
        "fixed": "12,000.50",
        "ungrouped": "12000.5",
        "stringValue": "12000",
        "negativeZero": "0.00",
    }


def test_value_worker_alignment_follows_format_and_resolved_type():
    card = (ROOT / "static" / "components" / "WorkerCard.js").read_text()
    grid = (ROOT / "static" / "components" / "BullpenTab.js").read_text()
    css = (ROOT / "static" / "style.css").read_text()

    assert "valueAlignment()" in card
    assert "kind === 'string-left'" in card
    assert "kind === 'string-right' || kind === 'number' || kind === 'currency'" in card
    assert ".worker-card-value-main--left" in css
    assert ".worker-card-value-main--right" in css
    assert "spreadsheetHasLabel()" in card
    assert "v-else-if=\"!usesSpreadsheetStyle || spreadsheetHasLabel\"" in card
    assert "spreadsheetValueAlignment()" in card
    assert "if (kind === 'string-left') return 'left';" in card
    assert "spreadsheetValueAlignment() {\n      const kind = String(this.worker?.format?.kind || 'general');\n      if (kind === 'string-left') return 'left';\n      return 'right';" in card
    assert "'worker-card-compact-value--' + spreadsheetValueAlignment" in card
    assert "interactiveTarget && !e.target.closest('.worker-card-compact-value-button')" in grid


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
    assert "Clear History" in card
    assert "menuClearValueHistory()" in card
    assert "if (!this.valueHistoryEnabled) return;" in card
    assert '@click="clearValueHistory"' in card
    assert 'class="value-history-delete-btn"' in card
    assert '@click="deleteValueHistoryRow(index)"' in card
    assert "saveValueHistory(history)" in card
    assert "deleteValueHistoryRow(index)" in card
    assert "clearValueHistory()" in card
    assert "this.$root.saveWorkerConfig({ slot: this.slotIndex, fields: { history: nextHistory } });" in card
    assert "if (!window.confirm('Clear all value history rows?')) return;" in card
    assert "valueHistoryRows()" in card
    assert "if (!this.valueHistoryEnabled) return [];" in card
    assert "exportValueHistoryCsv()" in card
    assert 'class="value-history-table"' in card
    assert 'a.download = `${this.valueHistoryFilenameBase()}.csv`;' in card
    assert "buildChartPoints(points, width, height, inset)" in card
    assert ".worker-card-value-sparkline-button {" in css
    sparkline_button_styles = css.split(".worker-card-value-sparkline-button {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 34px;" in sparkline_button_styles
    assert "height: auto;" in sparkline_button_styles
    assert "min-height: 34px;" in sparkline_button_styles
    assert ".value-graph-modal {" in css
    assert ".value-graph-chart {" in css
    assert ".value-history-pane {" in css
    assert ".value-history-table {" in css
    assert ".value-history-delete-btn {" in css


def test_value_history_delete_and_clear_save_filtered_history():
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
  WorkerCard: undefined,
  window: {{ confirm: () => true }},
  document: {{}},
  URL: {{}},
}};
vm.createContext(context);
vm.runInContext(source + `
  const methods = WorkerCard.methods;
  const computed = WorkerCard.computed;
  const component = {{
    isValue: true,
    slotIndex: 4,
    valueGraphOpen: true,
    worker: {{
      save_history: true,
      history: [
        {{ value: 1, value_type: 'number', resolved_value_type: 'number', updated_at: '2026-06-17T10:00:00Z' }},
        {{ value: 2, value_type: 'number', resolved_value_type: 'number', updated_at: '2026-06-17T11:00:00Z' }},
        {{ value: 3, value_type: 'number', resolved_value_type: 'number', updated_at: '2026-06-17T12:00:00Z' }},
      ],
    }},
    $root: {{ saveWorkerConfig(payload) {{ globalThis.__calls.push(payload); }} }},
    formatHistoryTimestamp(value) {{ return value; }},
    valueHistoryEnabled: true,
    closeValueGraph: methods.closeValueGraph,
    saveValueHistory: methods.saveValueHistory,
    deleteValueHistoryRow: methods.deleteValueHistoryRow,
    clearValueHistory: methods.clearValueHistory,
  }};
  Object.defineProperty(component, 'valueHistoryRows', {{
    get() {{ return computed.valueHistoryRows.call(component); }},
  }});
  globalThis.__calls = [];
  methods.deleteValueHistoryRow.call(component, 1);
  methods.clearValueHistory.call(component);
  globalThis.__result = {{ calls: globalThis.__calls, valueGraphOpen: component.valueGraphOpen }};
`, context);
process.stdout.write(JSON.stringify(context.__result));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["calls"][0] == {
        "slot": 4,
        "fields": {
            "history": [
                {"value": 1, "value_type": "number", "resolved_value_type": "number", "updated_at": "2026-06-17T10:00:00Z"},
                {"value": 3, "value_type": "number", "resolved_value_type": "number", "updated_at": "2026-06-17T12:00:00Z"},
            ],
        },
    }
    assert payload["calls"][1] == {"slot": 4, "fields": {"history": []}}
    assert payload["valueGraphOpen"] is False


def test_value_shortcut_editor_parses_and_creates_values():
    text = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert "valueShortcutEditor: null" in text
    assert "printableValueShortcutKey(e)" in text
    assert "parseValueShortcutText(text)" in text
    assert "const colon = raw.indexOf(':');" in text
    assert "const slash = label.lastIndexOf('/');" in text
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
    labelLessTime: BullpenTab.methods.parseValueShortcutText(':12:30'),
    labelLessUrl: BullpenTab.methods.parseValueShortcutText(':https://example.test/a:b'),
    named: BullpenTab.methods.parseValueShortcutText('tax rate: 5.5'),
    unit: BullpenTab.methods.parseValueShortcutText('temp/f:32'),
    plain: BullpenTab.methods.parseValueShortcutText('foo'),
    emptyAfterColon: BullpenTab.methods.parseValueShortcutText('name:'),
    rangeFormula: BullpenTab.methods.parseValueShortcutText('=SUM(C36:C37)'),
    stringColonFormula: BullpenTab.methods.parseValueShortcutText('="left:right"'),
    escapedFormula: BullpenTab.methods.parseValueShortcutText("'=SUM(C36:C37)"),
    namedFormula: BullpenTab.methods.parseValueShortcutText('total:=SUM(C36:C37)'),
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
    assert parsed["labelLessTime"]["fields"]["value"] == "12:30"
    assert parsed["labelLessUrl"]["fields"]["value"] == "https://example.test/a:b"
    assert parsed["named"]["fields"]["name"] == "tax rate"
    assert parsed["named"]["fields"]["value"] == "5.5"
    assert parsed["unit"]["fields"]["name"] == "temp"
    assert parsed["unit"]["fields"]["unit"] == "f"
    assert parsed["unit"]["fields"]["value"] == "32"
    assert parsed["plain"]["fields"]["name"] == ""
    assert parsed["plain"]["fields"]["value"] == "foo"
    assert parsed["emptyAfterColon"]["fields"]["name"] == "name"
    assert parsed["emptyAfterColon"]["fields"]["value"] is None
    assert parsed["rangeFormula"]["fields"] == {
        "name": "", "unit": "", "value": "=SUM(C36:C37)",
        "value_type": "auto", "format": {"kind": "general"},
    }
    assert parsed["stringColonFormula"]["fields"]["value"] == '="left:right"'
    assert parsed["escapedFormula"]["fields"]["value"] == "'=SUM(C36:C37)"
    assert parsed["namedFormula"]["fields"]["name"] == "total"
    assert parsed["namedFormula"]["fields"]["value"] == "=SUM(C36:C37)"


def test_all_letters_start_value_shortcut_editor_in_blank_cell():
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
  const methods = BullpenTab.methods;
  const letters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
  const results = {{}};
  for (const letter of letters) {{
    const component = {{
      selectedCell: {{ col: 2, row: 3 }},
      ghostCell: null,
      emptyMenuCoord: null,
      showLibrary: false,
      showGoTo: false,
      showHelp: false,
      opened: [],
      fitCount: 0,
      isWritableCoord(coord) {{ return !!coord; }},
      itemAtCoord() {{ return null; }},
      openValueShortcutEditor(coord, initialText) {{
        this.opened.push({{ coord, initialText }});
      }},
      fitOccupied() {{ this.fitCount += 1; }},
      jumpHome() {{}},
      valueShortcutTargetCoord: methods.valueShortcutTargetCoord,
      printableValueShortcutKey: methods.printableValueShortcutKey,
    }};
    const event = {{
      key: letter,
      metaKey: false,
      ctrlKey: false,
      altKey: false,
      defaultPrevented: false,
      target: null,
      preventDefault() {{ this.defaultPrevented = true; }},
    }};
    methods.onKeydown.call(component, event);
    results[letter] = {{ opened: component.opened, fitCount: component.fitCount, defaultPrevented: event.defaultPrevented }};
  }}
  globalThis.__results = results;
`, context);
process.stdout.write(JSON.stringify(context.__results));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    results = json.loads(result.stdout)

    for letter, payload in results.items():
        assert payload["defaultPrevented"] is True, letter
        assert payload["fitCount"] == 0, letter
        assert payload["opened"] == [{"coord": {"col": 2, "row": 3}, "initialText": letter}], letter


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
  rowText: {json.dumps("1\t2\t3")},
  columnText: {json.dumps("1\n2\n3")},
  raggedText: {json.dumps("a\tb\nc")},
}};
vm.createContext(context);
vm.runInContext(source + `
  const parse = BullpenTab.methods.parseWorksheetClipboardText;
  globalThis.__parsed = {{
    plain: parse(plainText),
    quoted: parse(quotedText),
    singleText: parse(singleText),
    rowText: parse(rowText),
    columnText: parse(columnText),
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
    assert parsed["singleText"] == [["not worksheet data"]]
    assert parsed["rowText"] == [["1", "2", "3"]]
    assert parsed["columnText"] == [["1"], ["2"], ["3"]]
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
  GridGeometry: {{
    coordKey: (col, row) => `${{col}},${{row}}`,
    coordToCellRef: (coord) => `${{String.fromCharCode(65 + coord.col)}}${{coord.row + 1}}`,
  }},
  pasteText: {json.dumps("1\t\t3\n4\t5\t6\n")},
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
    showPasteSuccess: methods.showPasteSuccess,
    itemAtCoord(coord) {{ return coord.col === 3 && coord.row === 2 ? {{ slotIndex: 8 }} : null; }},
    isWritableCoord(coord) {{ return coord && coord.col >= 0 && coord.row >= 0 && coord.col <= 100 && coord.row <= 100; }},
  }};
  globalThis.__calls = [];
  globalThis.__toasts = [];
  const scalar = methods.pasteWorksheetCells.call(component, {{ col: 0, row: 0 }}, '42');
  const pasted = methods.pasteWorksheetCells.call(component, {{ col: 4, row: 6 }}, pasteText);
  const rejected = methods.pasteWorksheetCells.call(component, {{ col: 2, row: 2 }}, conflictText);
  globalThis.__result = {{ scalar, pasted, rejected, calls: globalThis.__calls, toasts: globalThis.__toasts, liveMessage: component.liveMessage, emptyMenuCoord: component.emptyMenuCoord }};
`, context);
process.stdout.write(JSON.stringify(context.__result));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["scalar"] is True
    assert payload["pasted"] is True
    assert payload["rejected"] is False
    assert payload["emptyMenuCoord"] is None
    assert len(payload["calls"]) == 2
    assert [item["coord"] for item in payload["calls"][0]] == [{"col": 0, "row": 0}]
    assert payload["calls"][0][0]["worker"]["value"] == "42"
    assert [item["coord"] for item in payload["calls"][1]] == [
        {"col": 4, "row": 6},
        {"col": 6, "row": 6},
        {"col": 4, "row": 7},
        {"col": 5, "row": 7},
        {"col": 6, "row": 7},
    ]
    assert all(item["worker"]["type"] == "value" for item in payload["calls"][1])
    assert all(item["worker"]["name"] == "" for item in payload["calls"][1])
    assert [item["worker"]["value"] for item in payload["calls"][1]] == ["1", "3", "4", "5", "6"]
    assert payload["toasts"] == [
        {"message": "Pasted 1×1 range: 1 Value created", "type": "success"},
        {"message": "Pasted 2×3 range: 5 Values created, 1 blank cell skipped", "type": "success"},
        {"message": "Cannot paste: D3 is occupied", "type": "error"},
    ]
    assert payload["liveMessage"] == "Cannot paste: D3 is occupied"


def test_worker_grid_ctrl_v_uses_system_clipboard_for_worksheet_paste():
    text = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert '@paste="onPaste"' in text
    assert "e?.clipboardData?.getData?.('text/plain')" in text
    assert "this.pasteWorker(coord, { allowReplaceSingle: true });" not in text
    assert "Cannot paste:" in text
    assert "this.$root.addToast(message, 'error');" in text


def test_value_card_inline_edit_saves_and_reverts():
    text = (ROOT / "static" / "components" / "WorkerCard.js").read_text()

    assert "valueEditing: false" in text
    assert "valueEditIncludesName: false" in text
    assert '@keydown.enter.prevent.stop="commitValueEdit"' in text
    assert '@keydown.escape.prevent.stop="cancelValueEdit({ restoreGridFocus: true })"' in text
    assert text.count('@blur="onValueEditBlur"') >= 2
    assert "if (this.formulaHelpOpen) return;" in text
    assert "this._closeValueEdit = (e) => {" in text
    assert "document.addEventListener('pointerdown', this._closeValueEdit, true);" in text
    assert "document.removeEventListener('pointerdown', this._closeValueEdit, true);" in text
    assert "@click.stop=\"startValueEdit\"" in text
    assert "startCompactValueEdit()" in text
    assert "validateValueEditText(text)" in text
    assert "Enter a valid number." in text
    assert "fields: this.valueEditIncludesName" in text
    assert "? { name: parsed.name, unit: parsed.unit, value: parsed.value }" in text
    assert ": { value: parsed.value }" in text
    assert "this.cancelValueEdit({ restoreGridFocus: true });" in text
    assert "'value-edit-ended'" in text
    assert "renderLucideIcons(this.$el);" in text


def test_value_card_keyboard_cancel_restores_grid_focus_and_icons():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "components" / "WorkerCard.js"))}, 'utf8');
const context = {{
  console,
  isValueWorker: worker => worker?.type === 'value',
  __rendered: [],
}};
context.renderLucideIcons = el => context.__rendered.push(el);
vm.createContext(context);
vm.runInContext(source + `
  const methods = WorkerCard.methods;
  const emitted = [];
  const component = {{
    valueEditing: true,
    valueEditText: '41',
    valueEditError: 'old',
    valueEditIncludesName: true,
    $el: 'card-el',
    $emit(name) {{ emitted.push(name); }},
    $nextTick(fn) {{ fn(); }},
  }};
  methods.cancelValueEdit.call(component, {{ restoreGridFocus: true }});
  globalThis.__result = {{
    valueEditing: component.valueEditing,
    valueEditText: component.valueEditText,
    valueEditError: component.valueEditError,
    valueEditIncludesName: component.valueEditIncludesName,
    emitted,
    rendered: __rendered,
  }};
`, context);
process.stdout.write(JSON.stringify(context.__result));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload == {
        "valueEditing": False,
        "valueEditText": "",
        "valueEditError": "",
        "valueEditIncludesName": False,
        "emitted": ["value-edit-ended"],
        "rendered": ["card-el"],
    }


def test_bullpen_grid_focuses_after_value_edit_keyboard_end():
    text = (ROOT / "static" / "components" / "BullpenTab.js").read_text()

    assert '@value-edit-ended="onValueEditEnded(item)"' in text
    assert "onValueEditEnded(item) {" in text
    assert "if (item?.coord) this.selectWorker(item, { preserveMultiple: true });" in text
    assert "this.focusViewport();" in text


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
    valueEditText: 'tax rate/percent:6.4',
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
        "fields": {"name": "tax rate", "unit": "percent", "value": "6.4"},
    }]
    assert payload["cancelled"] is True


def test_value_card_compact_formula_parser_preserves_colons_and_source():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    script = f"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync({json.dumps(str(ROOT / "static" / "components" / "WorkerCard.js"))}, 'utf8');
const context = {{
  console,
  isValueWorker: worker => worker?.type === 'value',
  renderLucideIcons: () => {{}},
}};
vm.createContext(context);
vm.runInContext(source + `
  const methods = WorkerCard.methods;
  const calls = [];
  const component = {{
    worker: {{ type: 'value', name: 'total', unit: 'usd', value_type: 'auto', formula: {{ source: '=SUM(C36:C37)' }} }},
    storedValueText: '7',
    valueEditIncludesName: true,
    valueEditText: 'net total/eur:=SUM(C36:C37)',
    slotIndex: 8,
    parseValueEditText: methods.parseValueEditText,
    validateValueEditText: methods.validateValueEditText,
    cancelValueEdit() {{ this.cancelled = true; }},
    $root: {{ saveWorkerConfig(payload) {{ calls.push(payload); }} }},
  }};
  globalThis.__result = {{
    parsed: methods.parseValueEditText.call(component, '=SUM(C36:C37)'),
    namedParsed: methods.parseValueEditText.call(component, 'net total/eur:=SUM(C36:C37)'),
    escaped: methods.parseValueEditText.call(component, "'=SUM(C36:C37)"),
    sourceText: WorkerCard.computed.valueEditSourceText.call(component),
    roundTrips: [
      '=2+2*3',
      '=SUM(C36:C37)',
      '="Hello, world: [ok] (v1)! #50% / path?"',
    ].map(source => {{
      const roundTripCalls = [];
      const blank = {{
        worker: {{ type: 'value', name: '', unit: '', value_type: 'auto', formula: {{ source }} }},
        storedValueText: 'computed',
        valueEditIncludesName: true,
        slotIndex: 9,
        parseValueEditText: methods.parseValueEditText,
        validateValueEditText: methods.validateValueEditText,
        cancelValueEdit() {{}},
        $root: {{ saveWorkerConfig(payload) {{ roundTripCalls.push(payload); }} }},
      }};
      blank.valueEditText = WorkerCard.computed.valueEditSourceText.call(blank);
      methods.commitValueEdit.call(blank);
      return {{ source, editText: blank.valueEditText, calls: roundTripCalls }};
    }}),
  }};
  methods.commitValueEdit.call(component);
  globalThis.__result.calls = calls;
`, context);
process.stdout.write(JSON.stringify(context.__result));
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["parsed"] == {"name": "total", "unit": "usd", "value": "=SUM(C36:C37)"}
    assert payload["namedParsed"] == {"name": "net total", "unit": "eur", "value": "=SUM(C36:C37)"}
    assert payload["escaped"] == {"name": "total", "unit": "usd", "value": "'=SUM(C36:C37)"}
    assert payload["sourceText"] == "total/usd:=SUM(C36:C37)"
    for item in payload["roundTrips"]:
        assert item["editText"] == item["source"]
        assert item["calls"] == [{
            "slot": 9,
            "fields": {"formula_source": item["source"], "name": "", "unit": ""},
        }]
    assert payload["calls"] == [{
        "slot": 8,
        "fields": {"formula_source": "=SUM(C36:C37)", "name": "net total", "unit": "eur"},
    }]
