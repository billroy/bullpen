"""Regression checks for the project Stats tab."""

import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_stats_tab_component_is_loaded_before_app():
    text = _read("static/index.html")
    assert '<script src="/components/StatsTab.js"></script>' in text
    assert text.index('/components/StatsTab.js') < text.index('/app.js')


def test_commits_tab_is_before_stats():
    text = _read("static/app.js")
    files = "{ id: 'files', label: 'Files', icon: 'folder' }"
    stats = "{ id: 'stats', label: 'Stats', icon: 'chart-no-axes-column' }"
    commits = "{ id: 'commits', label: 'Git', icon: 'git-branch' }"
    assert files in text
    assert stats in text
    assert commits in text
    assert text.index(files) < text.index(commits) < text.index(stats)


def test_stats_tab_uses_archived_ticket_cache_and_refreshes_archive_scope():
    app = _read("static/app.js")
    component = _read("static/components/StatsTab.js")
    assert "StatsTab," in app
    assert 'v-if="activeWorkspaceId && activeTab === \'stats\'"' in app
    assert ':archived-tasks="workspaces[activeWorkspaceId]?.archivedTasks || []"' in app
    assert "if (tabId === 'stats' && activeWorkspaceId.value)" in app
    assert "socket.emit('task:list', _wsData({ scope: 'archived' }));" in app
    assert "props: ['tasks', 'archivedTasks', 'columns', 'layout', 'workspaceId']" in component
    assert "emits: ['select-task']" in component


def test_stats_tab_renders_required_dashboard_panes():
    text = _read("static/components/StatsTab.js")
    assert "Open tickets" in text
    assert "Archived tickets" in text
    assert "Daily archived tickets" in text
    assert "Daily open tickets" in text
    assert "Daily archived total ticket time" in text
    assert "Archived ticket tokens" in text
    assert "Recent Archive" in text
    assert "Current Load" in text


def test_stats_tab_trends_supports_period_selector_options():
    text = _read("static/components/StatsTab.js")
    assert "selectedPeriodKey: '14d'" in text
    assert "{ key: '1d', label: '1d', days: 1, title: 'Last day' }" in text
    assert "{ key: '7d', label: '7d', days: 7, title: 'Last 7 days' }" in text
    assert "{ key: '14d', label: '14d', days: 14, title: 'Last 14 days' }" in text
    assert "{ key: '30d', label: '30d', days: 30, title: 'Last 30 days' }" in text
    assert "{ key: '90d', label: '90d', days: 90, title: 'Last 90 days' }" in text
    assert "{ key: '6m', label: '6m', months: 6, title: 'Last 6 months' }" in text
    assert "{ key: '1y', label: '1y', years: 1, title: 'Last year' }" in text
    assert "{ key: '2y', label: '2y', years: 2, title: 'Last 2 years' }" in text
    assert "{ key: 'all', label: 'all', all: true, title: 'All time' }" in text
    assert 'aria-label="Trend period"' in text
    assert ':aria-pressed="option.key === selectedPeriodKey"' in text


def test_stats_tab_all_period_covers_earliest_trend_date():
    node = shutil.which("node")
    if not node:
        raise AssertionError("node is required for StatsTab computed regression checks")

    source_path = json.dumps(str(ROOT / "static" / "components" / "StatsTab.js"))
    script = """
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(__SOURCE_PATH__, 'utf8');

const context = {
  console,
  getReportedTaskTimeMs: (task) => Number(task.reported_task_time_ms || 0),
  formatTaskDuration: (value) => `${value}ms`,
};

vm.createContext(context);
vm.runInContext(`${source}\\n;globalThis.__StatsTab = StatsTab;`, context);

const component = context.__StatsTab;
const instance = {
  ...component.data.call({}),
  tasks: [
    { id: 'live-old', created_at: '2024-01-10T12:00:00' },
    { id: 'live-new', created_at: '2024-01-12T12:00:00' },
  ],
  archivedTasks: [
    { id: 'archived-old', archived_at: '2023-12-30T09:00:00', tokens: 5, reported_task_time_ms: 2000 },
    { id: 'archived-new', updated_at: '2024-01-01T00:00:00', tokens: 7, reported_task_time_ms: 3000 },
  ],
  columns: [],
  layout: { slots: [] },
};

for (const [name, getter] of Object.entries(component.computed || {})) {
  Object.defineProperty(instance, name, { get: () => getter.call(instance) });
}
for (const [name, method] of Object.entries(component.methods || {})) {
  instance[name] = method.bind(instance);
}

instance.selectedPeriodKey = 'all';
const charts = instance.sparklineCharts;
const payload = {
  labels: instance.periodOptions.map(option => option.label),
  title: instance.trendWindowLabel,
  first: instance.dayKeys[0],
  hasEarliestArchiveDate: instance.dayKeys.includes('2023-12-30'),
  totals: charts.map(chart => chart.total),
};

console.log(JSON.stringify(payload));
""".replace("__SOURCE_PATH__", source_path)

    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)
    assert payload["labels"][-4:] == ["6m", "1y", "2y", "all"]
    assert payload["title"] == "All time"
    assert payload["first"] == "2023-12-30"
    assert payload["hasEarliestArchiveDate"] is True
    assert payload["totals"] == [2, 2, 5000, 12]


def test_stats_tab_trends_include_date_axis_ticks():
    text = _read("static/components/StatsTab.js")
    assert "class=\"stats-sparkline-tick\"" in text
    assert "class=\"stats-spark-axis\"" in text
    assert "axisTicks()" in text
    assert "formatDayKey(dayKey)" in text


def test_stats_tab_archived_time_trend_uses_reported_task_time_formatting():
    text = _read("static/components/StatsTab.js")
    assert "taskTimeValue(task)" in text
    assert "getReportedTaskTimeMs" in text
    assert "totalType: 'duration'" in text
    assert "formatSparkTotal(chart)" in text
    assert "formatTaskDuration(chart.total)" in text
