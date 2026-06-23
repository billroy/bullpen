"""Source-level checks for Value Change trigger frontend wiring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return (ROOT / path).read_text()


def test_worker_config_modal_exposes_value_change_trigger_controls():
    text = _read("static/components/WorkerConfigModal.js")

    assert '<option v-if="canUseValueChangeTrigger" value="on_value_change">On Value Change</option>' in text
    assert 'v-if="!isService && !isValue && canUseValueChangeTrigger && form.activation === \'on_value_change\'"' in text
    assert '<option value="any:">Any Value</option>' in text
    assert 'v-for="option in valueTriggerOptions"' in text
    assert 'v-model="form.value_trigger_fire_on_noop"' in text
    assert 'v-model.number="form.value_trigger_cooldown_seconds"' in text
    assert 'v-model="form.value_trigger_condition_operator"' in text
    assert 'v-model="form.value_trigger_condition_value"' in text
    assert '<option value="contains">Contains</option>' in text
    assert '<option :value="\'<\'">&lt;</option>' in text
    assert '<option :value="\'<=\'">&lt;=</option>' in text
    assert '<option value="==">==</option>' in text
    assert '<option value=">">&gt;</option>' in text
    assert '<option value=">=">&gt;=</option>' in text
    assert "Less than" not in text
    assert "Greater than" not in text


def test_worker_config_modal_saves_named_and_unnamed_value_refs():
    text = _read("static/components/WorkerConfigModal.js")

    assert "valueTriggerOptions()" in text
    assert "const scope = name ? 'name' : 'coord';" in text
    assert "key: `${scope}:${encodeURIComponent(ref)}`" in text
    assert "this.form.value_trigger_scope = ['any', 'name', 'coord'].includes(scope) ? scope : 'any';" in text
    assert "fields.value_trigger_scope === 'coord'" in text
    assert "window.GridGeometry?.parseCellRef?.(fields.value_trigger_ref)" in text


def test_worker_config_modal_drops_trigger_fields_when_not_applicable():
    text = _read("static/components/WorkerConfigModal.js")

    assert "if (!this.canUseValueChangeTrigger || fields.activation !== 'on_value_change')" in text
    assert "delete fields.value_trigger_scope;" in text
    assert "delete fields.value_trigger_ref;" in text
    assert "delete fields.value_trigger_fire_on_noop;" in text
    assert "delete fields.value_trigger_cooldown_seconds;" in text
    assert "delete fields.value_trigger_condition_operator;" in text
    assert "delete fields.value_trigger_condition_value;" in text


def test_worker_config_modal_round_trips_value_trigger_condition_fields():
    text = _read("static/components/WorkerConfigModal.js")

    assert "value_trigger_condition_operator: w.value_trigger_condition_operator || 'any'" in text
    assert "value_trigger_condition_value: w.value_trigger_condition_value || ''" in text
    assert "fields.value_trigger_condition_operator = ['any', 'contains', '<', '<=', '==', '>', '>='].includes" in text
    assert "fields.value_trigger_condition_value = String(fields.value_trigger_condition_value || '').trim();" in text


def test_worker_config_modal_shows_value_trigger_condition_guidance():
    text = _read("static/components/WorkerConfigModal.js")

    assert "valueTriggerSelectedOption()" in text
    assert "valueTriggerConditionHint()" in text
    assert "valueTriggerConditionWarning()" in text
    assert "Contains compares against the value text." in text
    assert "Text values use alphabetic ordering." in text
    assert "Comparison value is not a valid number yet." in text
    assert "valueTriggerConditionOperator !== 'any'" in text


def test_worker_config_modal_groups_value_trigger_controls():
    text = _read("static/components/WorkerConfigModal.js")
    css = _read("static/style.css")

    assert 'class="form-row worker-trigger-row"' in text
    assert 'v-if="!isService && !isValue && canUseValueChangeTrigger && form.activation === \'on_value_change\'"' in text
    assert 'class="value-trigger-controls"' in text
    assert ".worker-trigger-row" in css
    assert "flex-wrap: wrap;" in css
    assert ".value-trigger-controls" in css
    assert "grid-template-columns: repeat(12, minmax(0, 1fr));" in css
    assert "width: 100%;" in css
    assert ".value-trigger-comparison" in css
