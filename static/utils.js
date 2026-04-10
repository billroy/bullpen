function agentColor(agent) {
  return { claude: '#da7756', codex: '#5b6fd6' }[agent] || '#6B7280';
}

function isHumanWorker(worker) {
  return worker?.is_human === true || worker?.type === 'human' || worker?.agent === 'human';
}

function getWorkerTypeIcon(worker) {
  return isHumanWorker(worker) ? 'user' : 'bot';
}

function renderLucideIcons(rootEl) {
  if (!window.lucide?.createIcons) return;
  window.lucide.createIcons({ attrs: { 'stroke-width': 2 }, root: rootEl || document });
}
