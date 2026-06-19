"""Source-level checks for Value Change trigger frontend wiring."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return (ROOT / path).read_text()


def test_worker_config_modal_exposes_value_change_trigger_controls():
    text = _read("static/components/WorkerConfigModal.js")

    assert '<option v-if="canUseValueChangeTrigger" value="on_value_change">On Value Change</option>' in text
    assert 'v-if="canUseValueChangeTrigger && form.activation === \'on_value_change\'"' in text
    assert '<option value="any:">Any Value</option>' in text
    assert 'v-for="option in valueTriggerOptions"' in text
    assert 'v-model="form.value_trigger_fire_on_noop"' in text
    assert 'v-model.number="form.value_trigger_cooldown_seconds"' in text


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
