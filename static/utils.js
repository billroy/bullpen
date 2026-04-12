window.BULLPEN_TASK_DND_MIME = 'application/x-bullpen-task-id';

const MODEL_OPTIONS = {
  claude: [
    'claude-opus-4-6', 'claude-opus-4-5-20250514',
    'claude-sonnet-4-6', 'claude-sonnet-4-5-20250514',
    'claude-haiku-4-5-20250414',
  ],
  codex: ['gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2'],
};

function agentColor(agent) {
  return { claude: '#da7756', codex: '#5b6fd6' }[agent] || '#6B7280';
}

function isHumanWorker(worker) {
  return worker?.is_human === true || worker?.type === 'human' || worker?.agent === 'human';
}

function getWorkerTypeIcon(worker) {
  return isHumanWorker(worker) ? 'user' : 'bot';
}

function getColumnIcon(col) {
  const workerColumns = new Set(['assigned', 'in_progress']);
  return col?.icon || (workerColumns.has(col?.key) ? 'bot' : 'user');
}

function renderLucideIcons(rootEl) {
  if (!window.lucide?.createIcons) return;
  const root = rootEl?.querySelectorAll ? rootEl : document;
  window.lucide.createIcons({ attrs: { 'stroke-width': 2 }, root });
}
