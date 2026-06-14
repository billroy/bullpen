"""Source-level checks for initial value worker frontend wiring."""

import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_value_worker_type_metadata_is_registered():
    text = (ROOT / "static" / "utils.js").read_text()

    assert "value: '#86efac'" in text
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


def test_value_worker_config_modal_has_value_fields_only():
    text = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text()

    assert "isValue()" in text
    assert '<span v-if="isValue" class="worker-type-badge">Value</span>' in text
    assert '<template v-if="isValue">' in text
    assert 'v-model="form.value"' in text
    assert 'v-model="form.value_type"' in text
    assert 'v-model="form.format.kind"' in text
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

    assert 'v-if="showCompactValue" class="worker-card-compact-value"' in card
    assert "return this.isValue && this.effectiveLayoutMode === 'small';" in card
    assert "{{ valueDisplay || 'Empty' }}" in card
    assert ".worker-card-compact-value {" in css
    assert "text-align: right;" in css
    assert "text-overflow: ellipsis;" in css


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


def test_value_card_inline_edit_saves_and_reverts():
    text = (ROOT / "static" / "components" / "WorkerCard.js").read_text()

    assert "valueEditing: false" in text
    assert '@keydown.enter.prevent.stop="commitValueEdit"' in text
    assert '@keydown.escape.prevent.stop="cancelValueEdit"' in text
    assert "@click.stop=\"startValueEdit\"" in text
    assert "validateValueEditText(text)" in text
    assert "Enter a valid number." in text
    assert "fields: { value: String(this.valueEditText) }" in text
    assert "this.cancelValueEdit();" in text
