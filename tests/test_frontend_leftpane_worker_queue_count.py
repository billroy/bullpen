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


def test_leftpane_worker_roster_uses_grid_single_worker_menu_actions():
    text = LEFTPANE_PATH.read_text(encoding="utf-8")
    assert "roster-worker-menu-btn" in text
    assert "openRosterWorkerMenuSlot === w.slot" in text
    assert '<div class="worker-menu-section-label">This Worker</div>' in text
    assert 'class="worker-menu-item" @click="rosterMenuEdit(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuRun(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuRestart(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuWatch(w.slot)"' in text
    assert 'class="worker-menu-item" :disabled="!serviceSiteUrl(w)" @click="rosterMenuOpenSite(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuStop(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuPause(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuUnpause(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuDuplicate(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuCopyWorker(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuExportWorker(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuCopyTo(w.slot)"' in text
    assert 'class="worker-menu-item" @click="rosterMenuMoveTo(w.slot)"' in text
    assert 'class="worker-menu-item worker-menu-danger" @click="rosterMenuDelete(w.slot)"' in text


def test_leftpane_worker_roster_emits_app_level_worker_menu_events():
    left_pane = LEFTPANE_PATH.read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "'configure-worker'" in left_pane
    assert "'open-focus'" in left_pane
    assert "'transfer-worker'" in left_pane
    assert "'copy-worker'" in left_pane
    assert '@configure-worker="configureSlot = $event"' in app
    assert '@open-focus="openFocusTab"' in app
    assert '@transfer-worker="openTransfer"' in app
    assert '@copy-worker="copyWorkerFromLeftPane"' in app
    assert "function copyWorkerFromLeftPane(slot)" in app


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


def test_leftpane_worker_menu_rules_match_grid_worker_types():
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
  window: { addEventListener() {}, removeEventListener() {}, getServiceSiteUrl: worker => worker.port ? `http://127.0.0.1:${worker.port}` : '', localStorage: { getItem: () => null, setItem() {} } },
};
vm.createContext(context);
vm.runInContext(src + '\\nglobalThis.LeftPane = LeftPane;', context);
const methods = context.LeftPane.methods;
const cases = {
  aiIdle: { type: 'ai', state: 'idle', taskQueueLength: 2 },
  aiWorking: { type: 'ai', state: 'working', taskQueueLength: 1 },
  serviceRunning: { type: 'service', service_state: { state: 'running' }, port: 5173, taskQueueLength: 0 },
  serviceStopped: { type: 'service', service_state: { state: 'stopped' }, taskQueueLength: 0 },
  marker: { type: 'marker', state: 'idle', taskQueueLength: 0 },
  value: { type: 'value', state: 'idle', taskQueueLength: 0 },
  evalWorker: { type: 'eval', state: 'idle', taskQueueLength: 0 },
};
const out = {
  aiIdleCanStart: methods.canStartWorker(cases.aiIdle),
  aiIdleRunLabel: methods.runMenuLabel(cases.aiIdle),
  aiWorkingCanStop: methods.canStopWorker(cases.aiWorking),
  serviceRunningCanRestart: methods.canRestartWorker(cases.serviceRunning),
  serviceRunningCanWatch: methods.canWatchWorker(cases.serviceRunning),
  serviceRunningCanStop: methods.canStopWorker(cases.serviceRunning),
  serviceRunningSite: methods.serviceSiteUrl(cases.serviceRunning),
  serviceStoppedCanMove: methods.canMoveWorker(cases.serviceStopped),
  markerCanStart: methods.canStartWorker(cases.marker),
  markerCanPause: methods.canPauseWorker(cases.marker),
  valueCanStart: methods.canStartWorker(cases.value),
  valueCanPause: methods.canPauseWorker(cases.value),
  evalCanPause: methods.canPauseWorker(cases.evalWorker),
};
process.stdout.write(JSON.stringify(out));
""" % {
        "path": json.dumps(str(LEFTPANE_PATH)),
    }
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)

    assert out["aiIdleCanStart"] is True
    assert out["aiIdleRunLabel"] == "Run next (2)"
    assert out["aiWorkingCanStop"] is True
    assert out["serviceRunningCanRestart"] is True
    assert out["serviceRunningCanWatch"] is True
    assert out["serviceRunningCanStop"] is True
    assert out["serviceRunningSite"] == "http://127.0.0.1:5173"
    assert out["serviceStoppedCanMove"] is True
    assert out["markerCanStart"] is False
    assert out["markerCanPause"] is False
    assert out["valueCanStart"] is False
    assert out["valueCanPause"] is False
    assert out["evalCanPause"] is False
