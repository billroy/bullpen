"""Regression checks for left-pane worker roster queue count labels."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LEFTPANE_PATH = ROOT / "static" / "components" / "LeftPane.js"


def test_leftpane_worker_status_label_includes_working_queue_count():
    text = LEFTPANE_PATH.read_text(encoding="utf-8")
    assert 'workerStatusLabel(w)' in text
    assert 'workerStatusClass(w)' in text
    assert "workerStatusLabel(worker)" in text
    assert "paused: s.paused === true," in text
    assert "activation: s.activation," in text
    assert "if (worker?.paused === true) return 'PAUSED';" in text
    assert "return 'WAITING FOR RUN';" in text
    assert "if (state === 'RETRYING')" in text
    assert "return attempt && max ? `${state} (${attempt}/${max})` : state;" in text
    assert "if (state !== 'WORKING') return state;" in text
    assert "const queueCount = Math.max(1, Number(worker?.taskQueueLength || 0));" in text
    assert "return `${state} (${queueCount})`;" in text
    assert "workerStatusClass(worker)" in text


def test_leftpane_worker_status_labels_match_grid_overrides():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")

    script = """
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(%(path)s, 'utf8');
const context = {
  agentColor: () => '',
  workerColor: () => '',
  getWorkerTypeIcon: () => 'bot',
  window: { addEventListener() {}, removeEventListener() {}, localStorage: { getItem: () => null, setItem() {} } },
};
vm.createContext(context);
vm.runInContext(src + '\\nglobalThis.LeftPane = LeftPane;', context);
const layout = {
  slots: [
    { name: 'Paused worker', type: 'ai', state: 'idle', paused: true, task_queue: [] },
    { name: 'Manual held', type: 'ai', state: 'idle', paused: false, activation: 'manual', task_queue: ['t1'] },
    { name: 'Working worker', type: 'ai', state: 'working', paused: false, task_queue: ['t2', 't3'] },
  ],
};
const config = { grid: { cols: 3 } };
const component = context.LeftPane;
const self = { layout, config };
const workers = component.computed.workerList.call(self);
const labels = workers.map(w => ({
  name: w.name,
  paused: w.paused,
  activation: w.activation,
  label: component.methods.workerStatusLabel(w),
  statusClass: component.methods.workerStatusClass(w),
}));
process.stdout.write(JSON.stringify(labels));
""" % {
        "path": json.dumps(str(LEFTPANE_PATH)),
    }
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    labels = {item["name"]: item for item in json.loads(result.stdout)}

    assert labels["Paused worker"]["paused"] is True
    assert labels["Paused worker"]["label"] == "PAUSED"
    assert labels["Paused worker"]["statusClass"] == "idle"
    assert labels["Manual held"]["activation"] == "manual"
    assert labels["Manual held"]["label"] == "WAITING FOR RUN"
    assert labels["Working worker"]["label"] == "WORKING (2)"
