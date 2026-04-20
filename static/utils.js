window.BULLPEN_TASK_DND_MIME = 'application/x-bullpen-task-id';

const MODEL_OPTIONS = {
  claude: [
    'claude-opus-4-7',
    'claude-opus-4-6', 'claude-opus-4-5-20250514',
    'claude-sonnet-4-6', 'claude-sonnet-4-5-20250514',
    'claude-haiku-4-5-20251001',
  ],
  codex: ['gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2'],
  gemini: ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-pro'],
};

const DEFAULT_AGENT_COLORS = { claude: '#da7756', codex: '#5b6fd6', gemini: '#3c7bf4', shell: '#64748b', service: '#0f766e' };
window.DEFAULT_AGENT_COLORS = DEFAULT_AGENT_COLORS;
window.BULLPEN_AGENT_COLORS = (window.Vue && window.Vue.reactive)
  ? window.Vue.reactive({ overrides: {} })
  : { overrides: {} };

function agentColor(agent) {
  const overrides = window.BULLPEN_AGENT_COLORS.overrides || {};
  return overrides[agent] || DEFAULT_AGENT_COLORS[agent] || '#6B7280';
}

function workerColorKey(worker) {
  if (worker?.type === 'shell') return 'shell';
  if (worker?.type === 'service') return 'service';
  return worker?.agent;
}

function workerColor(worker) {
  return agentColor(workerColorKey(worker));
}

function isHumanWorker(worker) {
  return worker?.is_human === true || worker?.type === 'human' || worker?.agent === 'human';
}

const BUILTIN_WORKER_TYPES = new Set(['ai', 'shell', 'service', 'eval', 'human']);

function isShellWorker(worker) {
  return worker?.type === 'shell';
}

function isServiceWorker(worker) {
  return worker?.type === 'service';
}

function isEvalWorker(worker) {
  return worker?.type === 'eval';
}

function isUnknownWorkerType(worker) {
  const type = worker?.type;
  if (!type) return false;
  return !BUILTIN_WORKER_TYPES.has(type);
}

function getWorkerTypeIcon(worker) {
  if (isHumanWorker(worker)) return 'user';
  if (isShellWorker(worker)) return 'terminal';
  if (isServiceWorker(worker)) return 'server-cog';
  if (isEvalWorker(worker)) return 'flask-conical';
  if (isUnknownWorkerType(worker)) return 'circle-help';
  return 'bot';
}

function workerTypeLabel(worker) {
  if (isShellWorker(worker)) return 'Shell';
  if (isServiceWorker(worker)) return 'Service';
  if (isEvalWorker(worker)) return 'Eval';
  if (isHumanWorker(worker)) return 'Human';
  if (isUnknownWorkerType(worker)) return worker.type;
  return 'AI';
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
