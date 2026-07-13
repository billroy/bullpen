window.BULLPEN_TASK_DND_MIME = 'application/x-bullpen-task-id';
window.BULLPEN_TASK_DRAG_ACTIVE = false;
window.BULLPEN_TASK_DRAG_TASK_ID = null;

const MODEL_OPTIONS = {
  antigravity: [
    'Gemini 3.5 Flash (Medium)',
    'Gemini 3.5 Flash (High)',
    'Gemini 3.5 Flash (Low)',
    'Gemini 3.1 Pro (Low)',
    'Gemini 3.1 Pro (High)',
    'Claude Sonnet 4.6 (Thinking)',
    'Claude Opus 4.6 (Thinking)',
    'GPT-OSS 120B (Medium)',
  ],
  claude: [
    'claude-opus-4-7',
    'claude-opus-4-6', 'claude-opus-4-5-20250514',
    'claude-sonnet-5',
    'claude-sonnet-4-6', 'claude-sonnet-4-5-20250514',
    'claude-haiku-4-5-20251001',
  ],
  codex: ['gpt-5.6', 'gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2'],
  opencode: [],
};

const AI_PROVIDER_OPTIONS = ['antigravity', 'claude', 'codex', 'opencode'];

function normalizedLastAiSelection(value) {
  if (!value || typeof value !== 'object') return null;
  const agent = String(value.agent || '').trim();
  const model = String(value.model || '').trim();
  if (!AI_PROVIDER_OPTIONS.includes(agent) || !model) return null;
  return { agent, model };
}

function withPreferredOption(options, preferred) {
  const values = Array.isArray(options) ? options.slice() : [];
  if (!preferred) return values;
  return [preferred, ...values.filter(value => value !== preferred)];
}

const DEFAULT_AGENT_COLORS = { antigravity: '#0f8b8d', claude: '#da7756', codex: '#5b6fd6', opencode: '#63b3ed', shell: '#64748b', service: '#0f766e', marker: '#c8b38c', notification: '#d7ad4a', value: '#166534' };
window.DEFAULT_AGENT_COLORS = DEFAULT_AGENT_COLORS;
window.BULLPEN_AGENT_COLORS = (window.Vue && window.Vue.reactive)
  ? window.Vue.reactive({ overrides: {} })
  : { overrides: {} };
const HEX_COLOR_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

function agentColor(agent) {
  const overrides = window.BULLPEN_AGENT_COLORS.overrides || {};
  return overrides[agent] || DEFAULT_AGENT_COLORS[agent] || '#6B7280';
}

function workerColorKey(worker) {
  if (worker?.type === 'shell') return 'shell';
  if (worker?.type === 'service') return 'service';
  if (worker?.type === 'marker') return 'marker';
  if (worker?.type === 'notification') return 'notification';
  if (worker?.type === 'value') return 'value';
  return worker?.agent;
}

function workerColor(worker) {
  const configured = typeof worker?.color === 'string' ? worker.color.trim() : '';
  if (configured && HEX_COLOR_RE.test(configured)) return configured.toLowerCase();
  return agentColor(configured || workerColorKey(worker));
}

function isHumanWorker(worker) {
  return worker?.is_human === true || worker?.type === 'human' || worker?.agent === 'human';
}

const BUILTIN_WORKER_TYPES = new Set(['ai', 'shell', 'service', 'marker', 'notification', 'value', 'eval', 'human']);

function isShellWorker(worker) {
  return worker?.type === 'shell';
}

function isServiceWorker(worker) {
  return worker?.type === 'service';
}

function isMarkerWorker(worker) {
  return worker?.type === 'marker';
}

function isNotificationWorker(worker) {
  return worker?.type === 'notification';
}

function isValueWorker(worker) {
  return worker?.type === 'value';
}

function getServiceSiteUrl(worker, locationLike = window.location) {
  if (!isServiceWorker(worker)) return '';
  const port = Number(worker?.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return '';
  const fallbackHost = String(locationLike?.hostname || '').trim() || '127.0.0.1';
  let url;
  try {
    url = new URL(String(locationLike?.href || ''));
  } catch (_err) {
    url = new URL(`http://${fallbackHost}`);
  }
  url.protocol = 'http:';
  url.port = String(port);
  url.pathname = '/';
  url.search = '';
  url.hash = '';
  return url.toString();
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
  if (isMarkerWorker(worker)) return 'square-dot';
  if (isNotificationWorker(worker)) return 'bell-ring';
  if (isValueWorker(worker)) return 'equal';
  if (isEvalWorker(worker)) return 'flask-conical';
  if (isUnknownWorkerType(worker)) return 'circle-help';
  return 'bot';
}

function workerTypeLabel(worker) {
  if (isShellWorker(worker)) return 'Shell';
  if (isServiceWorker(worker)) return 'Service';
  if (isMarkerWorker(worker)) return 'Marker';
  if (isNotificationWorker(worker)) return 'Notification';
  if (isValueWorker(worker)) return 'Value';
  if (isEvalWorker(worker)) return 'Eval';
  if (isHumanWorker(worker)) return 'Human';
  if (isUnknownWorkerType(worker)) return worker.type;
  return 'AI';
}

function notificationSummaryItems(worker) {
  if (!isNotificationWorker(worker)) return [];
  const config = worker?.notification && typeof worker.notification === 'object' ? worker.notification : {};
  const items = [];
  const speech = config.speech && typeof config.speech === 'object' ? config.speech : {};
  const sound = config.sound && typeof config.sound === 'object' ? config.sound : {};
  const flash = config.flash && typeof config.flash === 'object' ? config.flash : {};
  const toast = config.toast && typeof config.toast === 'object' ? config.toast : {};

  if (speech.enabled) {
    const text = String(speech.template || '').trim();
    items.push(`Say "${text || 'notification text'}"`);
  }
  if (sound.enabled) {
    const effect = String(sound.effect || 'done').trim() || 'done';
    items.push(`Play ${effect.replaceAll('_', ' ')} sound`);
  }
  if (flash.enabled) {
    const sequence = Array.isArray(flash.sequence) ? flash.sequence : [];
    const first = sequence.find(step => step && typeof step === 'object') || {};
    const color = String(first.color || '#facc15').trim() || '#facc15';
    const count = Math.max(1, sequence.length || 1);
    items.push(`Flash ${color} ${count} ${count === 1 ? 'time' : 'times'}`);
  }
  if (toast.enabled) {
    const text = String(toast.template || '').trim();
    items.push(`Show toast "${text || 'notification text'}"`);
  }
  return items;
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

window.getServiceSiteUrl = getServiceSiteUrl;
window.renderLucideIcons = renderLucideIcons;
window.getWorkerTypeIcon = getWorkerTypeIcon;
window.workerTypeLabel = workerTypeLabel;
window.notificationSummaryItems = notificationSummaryItems;
window.workerColor = workerColor;
window.isHumanWorker = isHumanWorker;
window.isValueWorker = isValueWorker;
window.getColumnIcon = getColumnIcon;

function formatTaskDuration(ms) {
  const totalMs = Number(ms);
  if (!Number.isFinite(totalMs) || totalMs <= 0) return '0s';
  const totalSeconds = Math.floor(totalMs / 1000);
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function getReportedTaskTimeMs(task) {
  const reported = Number(task?.reported_task_time_ms);
  if (Number.isFinite(reported) && reported > 0) return reported;
  const persisted = Number(task?.task_time_ms);
  if (Number.isFinite(persisted) && persisted > 0) return persisted;
  return 0;
}

window.formatTaskDuration = formatTaskDuration;
window.getReportedTaskTimeMs = getReportedTaskTimeMs;
