const { createApp, reactive, ref, computed } = Vue;

const app = createApp({
  components: {
    TopToolbar,
    LeftPane,
    KanbanTab,
    BullpenTab,
    FilesTab,
    CommitsTab,
    LiveAgentChatTab,
    WorkerFocusView,
    TaskCreateModal,
    TaskDetailPanel,
    WorkerConfigModal,
    WorkerTransferModal,
    ColumnManagerModal,
    ToastContainer,
  },
  setup() {
    const THEME_CATALOG = [
      { id: 'dark', label: 'Dark', mode: 'dark' },
      { id: 'light', label: 'Light', mode: 'light' },
      { id: 'light-ethereal', label: 'Light Ethereal', mode: 'light' },
      { id: 'light-stone-teal', label: 'Light Stone Teal', mode: 'light' },
      { id: 'light-ivory-olive', label: 'Light Ivory Olive', mode: 'light' },
      { id: 'dracula', label: 'Dracula', mode: 'dark' },
      { id: 'nord', label: 'Nord', mode: 'dark' },
      { id: 'gruvbox', label: 'Gruvbox Dark', mode: 'dark' },
      { id: 'tokyo-night', label: 'Tokyo Night', mode: 'dark' },
      { id: 'catppuccin', label: 'Catppuccin Mocha', mode: 'dark' },
      { id: 'github-dark', label: 'GitHub Dark', mode: 'dark' },
      { id: 'monokai', label: 'Monokai', mode: 'dark' },
      { id: 'one-dark', label: 'One Dark', mode: 'dark' },
      { id: 'one-dark-pro', label: 'One Dark Pro', mode: 'dark' },
      { id: 'everforest', label: 'Everforest Dark', mode: 'dark' },
      { id: 'ayu-dark', label: 'Ayu Dark', mode: 'dark' },
      { id: 'material-ocean', label: 'Material Ocean', mode: 'dark' },
      { id: 'night-owl', label: 'Night Owl', mode: 'dark' },
      { id: 'shades-of-purple', label: 'Shades of Purple', mode: 'dark' },
      { id: 'solarized', label: 'Solarized Dark', mode: 'dark' },
      { id: 'panda', label: 'Panda Theme', mode: 'dark' },
      { id: 'cobalt-2', label: 'Cobalt 2', mode: 'dark' },
    ];
    const THEME_IDS = new Set(THEME_CATALOG.map(t => t.id));
    const AMBIENT_PRESETS = Array.isArray(window.AMBIENT_PRESET_LIST) ? window.AMBIENT_PRESET_LIST : [];
    const AMBIENT_PRESET_KEYS = new Set(AMBIENT_PRESETS.map(p => p.key));

    function _normalizeAmbientPreset(value) {
      if (!value) return null;
      const preset = String(value);
      return AMBIENT_PRESET_KEYS.has(preset) ? preset : null;
    }

    function _normalizeAmbientVolume(value) {
      const num = Number(value);
      if (!Number.isFinite(num)) return 40;
      return Math.max(0, Math.min(100, Math.round(num)));
    }

    // Per-workspace backing store (not directly rendered)
    const workspaces = reactive({});  // workspaceId -> { workspace, config, layout, tasks, profiles, teams, filesVersion, unseenActivity }

    // Active view state — mirrors whichever workspace is active
    const state = reactive({
      workspace: '',
      config: { name: 'Bullpen', grid: { rows: 4, cols: 6 }, columns: [], ambient_preset: null, ambient_volume: 40 },
      layout: { slots: [] },
      tasks: [],
      profiles: [],
      teams: [],
      filesVersion: 0,
    });

    const activeWorkspaceId = ref(null);
    const projects = reactive([]);  // [{id, path, name}]

    function _defaultWsData() {
      return {
        workspace: '',
        config: { name: 'Bullpen', grid: { rows: 4, cols: 6 }, columns: [], ambient_preset: null, ambient_volume: 40 },
        layout: { slots: [] },
        tasks: [],
        archivedTasks: [],
        profiles: [],
        teams: [],
        filesVersion: 0,
        unseenActivity: 0,
      };
    }

    function _getWs(wsId) {
      if (!workspaces[wsId]) workspaces[wsId] = _defaultWsData();
      return workspaces[wsId];
    }

    function _syncToView(wsId) {
      const ws = workspaces[wsId];
      if (!ws) return;
      state.workspace = ws.workspace;
      state.config = ws.config;
      state.layout = ws.layout;
      state.tasks = ws.tasks;
      state.profiles = ws.profiles;
      state.teams = ws.teams;
      state.filesVersion = ws.filesVersion;
    }

    function _normalizeConfig(config) {
      const safe = { ...(config || {}) };
      safe.theme = _normalizeTheme(safe.theme || 'dark');
      safe.ambient_preset = _normalizeAmbientPreset(safe.ambient_preset);
      safe.ambient_volume = _normalizeAmbientVolume(safe.ambient_volume);
      return safe;
    }

    function _applyWorkspaceAmbient(wsId) {
      const ws = workspaces[wsId];
      if (!ws || !window.ambientAudio) return;
      const volume = _normalizeAmbientVolume(ws.config?.ambient_volume);
      const preset = _normalizeAmbientPreset(ws.config?.ambient_preset);
      window.ambientAudio.setVolume(volume / 100);
      if (preset) {
        if (!(window.ambientAudio._ambientActive && window.ambientAudio._ambientPreset === preset)) {
          window.ambientAudio.startAmbient(preset, 10);
        }
      } else {
        window.ambientAudio.stopAmbient();
      }
    }

    function _isActive(wsId) {
      return wsId === activeWorkspaceId.value;
    }

    const PRISM_DARK = 'https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css';
    const PRISM_LIGHT = 'https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism.min.css';
    function _normalizeTheme(themeId) {
      if (typeof themeId !== 'string') return 'dark';
      return THEME_IDS.has(themeId) ? themeId : 'dark';
    }
    function _themeMode(themeId) {
      return THEME_CATALOG.find(t => t.id === themeId)?.mode || 'dark';
    }
    function _applyTheme(themeId) {
      const next = _normalizeTheme(themeId);
      document.documentElement.setAttribute('data-theme', next);
      const prismLink = document.getElementById('prism-theme');
      if (prismLink) prismLink.href = _themeMode(next) === 'light' ? PRISM_LIGHT : PRISM_DARK;
    }
    function _applyWorkspaceTheme(wsId) {
      const ws = workspaces[wsId];
      _applyTheme(ws?.config?.theme || 'dark');
    }

    function _workspaceBaseName(workspacePath) {
      if (typeof workspacePath !== 'string') return '';
      const trimmed = workspacePath.trim();
      if (!trimmed) return '';
      const parts = trimmed.split(/[\\/]+/).filter(Boolean);
      return parts.length ? parts[parts.length - 1] : '';
    }

    function _updateDocumentTitle() {
      const project = _workspaceBaseName(state.workspace);
      document.title = project ? `Bullpen : ${project}` : 'Bullpen';
    }

    function switchWorkspace(wsId) {
      if (!workspaces[wsId]) return;
      activeWorkspaceId.value = wsId;
      workspaces[wsId].unseenActivity = 0;
      ticketListScope.value = 'live';
      _syncToView(wsId);
      _applyWorkspaceTheme(wsId);
      _applyWorkspaceAmbient(wsId);
      _updateDocumentTitle();
      if (socket?.connected) socket.emit('project:join', { workspaceId: wsId });
    }

    const connected = ref(false);
    const activeTab = ref('tasks');
    const ticketsViewMode = ref('kanban');
    const ticketListScope = ref('live');
    const leftPaneVisible = ref(true);
    const toasts = reactive([]);
    const showCreateModal = ref(false);
    const showColumnManager = ref(false);
    const selectedTaskId = ref(null);
    const configureSlot = ref(null);
    const transferSlot = ref(null);
    const transferMode = ref('copy');
    const quickCreateClearToken = ref(0);
    const pendingQuickCreates = reactive([]);

    // Worker Focus Mode state
    const outputBuffers = reactive({});  // keyed by slot index
    const focusTabs = reactive([]);      // [{slotIndex, workspaceId, label}]
    const chatTabs = reactive([]);
    let chatTabCounter = 0;
    let toastId = 0;

    function _newChatSessionId() {
      return 'chat-' + Math.random().toString(36).slice(2, 10) + '-' + Date.now();
    }

    function addLiveAgentTab({ activate = true } = {}) {
      chatTabCounter += 1;
      const id = 'chat-' + chatTabCounter;
      chatTabs.push({
        id,
        label: chatTabCounter === 1 ? 'Live Agent' : `Live Agent ${chatTabCounter}`,
        sessionId: _newChatSessionId(),
      });
      if (activate) activeTab.value = id;
    }

    function closeLiveAgentTab(tabId) {
      if (chatTabs.length <= 1) return;
      const idx = chatTabs.findIndex(t => t.id === tabId);
      if (idx < 0) return;
      chatTabs.splice(idx, 1);
      if (activeTab.value === tabId) {
        const fallback = chatTabs[idx] || chatTabs[idx - 1];
        activeTab.value = fallback ? fallback.id : 'tasks';
      }
    }

    // Seed the default chat tab without switching away from Tickets.
    addLiveAgentTab({ activate: false });

    const selectedTask = computed(() => {
      if (!selectedTaskId.value) return null;
      return state.tasks.find(t => t.id === selectedTaskId.value) || null;
    });

    const configureWorkerData = computed(() => {
      if (configureSlot.value === null) return null;
      return state.layout?.slots?.[configureSlot.value] || null;
    });

    // Socket.io
    const socket = io({
      transports: ['websocket'],
    });
    window._bullpenSocket = socket;

    socket.on('connect', () => { connected.value = true; });
    socket.on('disconnect', () => { connected.value = false; });
    // If the server rejects the upgrade (e.g. unauthenticated session),
    // Socket.IO emits connect_error. Bounce the user to the login page.
    socket.on('connect_error', (err) => {
      connected.value = false;
      const msg = (err && err.message) || '';
      // Only redirect on auth-style errors, not generic network blips.
      if (/auth|forbidden|unauthor/i.test(msg) || err === false) {
        window.location = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
        return;
      }
      // Unknown transport error: try the login page as a last resort if
      // the server returned the default "unauthorized" rejection.
      if (msg.toLowerCase().includes('reject')) {
        window.location = '/login';
      }
    });

    socket.on('state:init', (data) => {
      const wsId = data.workspaceId;
      const ws = _getWs(wsId);
      ws.workspace = data.workspace;
      ws.config = _normalizeConfig(data.config);
      ws.layout = data.layout;
      ws.tasks = data.tasks;
      ws.profiles = data.profiles || [];
      ws.teams = data.teams || [];

      // First workspace or explicitly requested switch becomes active
      if (!activeWorkspaceId.value || data.switchTo) {
        switchWorkspace(wsId);
      }

      if (_isActive(wsId)) {
        _syncToView(wsId);
        _applyWorkspaceTheme(wsId);
        _applyWorkspaceAmbient(wsId);
        _updateDocumentTitle();
      }
    });

    socket.on('task:created', (task) => {
      const wsId = task.workspaceId || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.tasks.push(task);
      if (!_isActive(wsId)) ws.unseenActivity++;
      if (_isActive(wsId)) {
        const idx = pendingQuickCreates.findIndex(p => p.title === task.title);
        if (idx >= 0) {
          pendingQuickCreates.splice(idx, 1);
          quickCreateClearToken.value++;
        }
      }
    });
    socket.on('task:updated', (task) => {
      const wsId = task.workspaceId || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      const idx = ws.tasks.findIndex(t => t.id === task.id);
      if (idx >= 0) ws.tasks[idx] = task;
      else ws.tasks.push(task);
      if (_isActive(wsId)) {
        // state.tasks is the same array ref, already updated
      } else {
        ws.unseenActivity++;
      }
      if (selectedTaskId.value === task.id) {
        // Force reactivity on active view
      }
    });
    socket.on('task:deleted', (data) => {
      const wsId = data.workspaceId || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.tasks = ws.tasks.filter(t => t.id !== data.id);
      if (_isActive(wsId)) state.tasks = ws.tasks;
      if (selectedTaskId.value === data.id) selectedTaskId.value = null;
      if (_isActive(wsId) && ticketListScope.value === 'archived') {
        socket.emit('task:list', _wsData({ scope: 'archived' }));
      }
    });
    socket.on('task:list', (data) => {
      const wsId = data.workspaceId || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.archivedTasks = Array.isArray(data.tasks) ? data.tasks : [];
    });

    socket.on('layout:updated', (layout) => {
      const wsId = layout.workspaceId || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.layout = layout;
      if (_isActive(wsId)) state.layout = layout;
      else ws.unseenActivity++;
    });
    socket.on('config:updated', (config) => {
      const wsId = config.workspaceId || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.config = _normalizeConfig(config);
      if (_isActive(wsId)) {
        state.config = ws.config;
        _applyWorkspaceTheme(wsId);
        _applyWorkspaceAmbient(wsId);
      }
    });
    socket.on('profiles:updated', (profiles) => {
      // profiles is an array, workspaceId may be on any element or absent
      const wsId = (Array.isArray(profiles) ? null : profiles?.workspaceId) || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.profiles = profiles;
      if (_isActive(wsId)) state.profiles = profiles;
    });
    socket.on('teams:updated', (teams) => {
      const wsId = (Array.isArray(teams) ? null : teams?.workspaceId) || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.teams = teams;
      if (_isActive(wsId)) state.teams = teams;
    });
    socket.on('error', (data) => { addToast(data.message, 'error'); });
    socket.on('projects:updated', (list) => {
      projects.splice(0, projects.length, ...list);
    });
    socket.on('project:removed', (data) => {
      delete workspaces[data.workspaceId];
      if (activeWorkspaceId.value === data.workspaceId) {
        // Switch to first available
        const firstId = projects[0]?.id;
        if (firstId) switchWorkspace(firstId);
      }
    });
    socket.on('files:changed', (data) => {
      const wsId = (data && data.workspaceId) || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.filesVersion++;
      if (_isActive(wsId)) state.filesVersion = ws.filesVersion;
    });

    // Worker output streaming
    function _ensureBuffer(slot) {
      if (!outputBuffers[slot]) outputBuffers[slot] = reactive([]);
    }
    socket.on('worker:output', (data) => {
      const slot = data.slot;
      _ensureBuffer(slot);
      outputBuffers[slot].push(...data.lines);
      // Cap at 5000 lines client-side
      if (outputBuffers[slot].length > 5000) {
        outputBuffers[slot].splice(0, outputBuffers[slot].length - 5000);
      }
    });
    socket.on('worker:output:catchup', (data) => {
      const slot = data.slot;
      _ensureBuffer(slot);
      outputBuffers[slot].length = 0;
      outputBuffers[slot].push(...(data.lines || []));
    });
    socket.on('worker:output:done', (data) => {
      const slot = data.slot;
      _ensureBuffer(slot);
      // Replace buffer with complete final output
      outputBuffers[slot].length = 0;
      outputBuffers[slot].push(...(data.lines || []));
    });

    // Helper to attach workspaceId to outgoing events
    function _wsData(data) {
      return { ...data, workspaceId: activeWorkspaceId.value };
    }

    // Task actions
    function createTask(data) { socket.emit('task:create', _wsData(data)); }
    function quickCreateTask(payload) {
      const title = typeof payload === 'string' ? payload.trim() : (payload?.title || '').trim();
      const description = typeof payload === 'string' ? '' : (payload?.description || '').trim();
      if (!title) return;
      pendingQuickCreates.push({ title, description });
      socket.emit('task:create', _wsData({ title, type: 'task', priority: 'normal', tags: [], description }));
    }
    function updateTask(data) { socket.emit('task:update', _wsData(data)); }
    function deleteTask(id) {
      const task = state.tasks.find(t => t.id === id);
      if (task && (task.status === 'assigned' || task.status === 'in-progress')) {
        if (!confirm(`Task "${task.title}" is ${task.status}. Delete anyway?`)) return;
      }
      socket.emit('task:delete', _wsData({ id }));
    }
    function archiveTask(id) { socket.emit('task:archive', _wsData({ id })); }
    function archiveDone() {
      const count = state.tasks.filter(t => t.status === 'done').length;
      if (count && confirm(`Archive ${count} done task(s)?`)) {
        socket.emit('task:archive-done', _wsData({}));
      }
    }
    function clearTaskOutput(id) { socket.emit('task:clear_output', _wsData({ id })); }
    function moveTask({ id, status }) { socket.emit('task:update', _wsData({ id, status })); }
    function selectTask(id) { selectedTaskId.value = id; }
    function setTicketListScope(scope) {
      const normalized = String(scope || '').trim().toLowerCase() === 'archived' ? 'archived' : 'live';
      ticketListScope.value = normalized;
      if (normalized === 'archived') {
        socket.emit('task:list', _wsData({ scope: 'archived' }));
      } else if (selectedTaskId.value) {
        const isLiveTaskSelected = state.tasks.some(t => t.id === selectedTaskId.value);
        if (!isLiveTaskSelected) selectedTaskId.value = null;
      }
    }

    // Worker actions
    function addWorker({ slot, profile }) { socket.emit('worker:add', _wsData({ slot, profile })); }
    function removeWorker(slot) {
      const worker = state.layout?.slots?.[slot];
      if (worker?.task_queue?.length) {
        if (!confirm(`Worker "${worker.name}" has ${worker.task_queue.length} task(s) queued. Remove anyway?`)) return;
      }
      socket.emit('worker:remove', _wsData({ slot }));
    }
    function moveWorker(from, to) { socket.emit('worker:move', _wsData({ from, to })); }
    function duplicateWorker(slot) { socket.emit('worker:duplicate', _wsData({ slot })); }
    function openTransfer({ slot, mode }) {
      transferSlot.value = slot;
      transferMode.value = mode;
    }
    async function transferWorker(payload) {
      try {
        const resp = await fetch('/api/worker/transfer', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) {
          addToast(data.error || 'Transfer failed', 'error');
          return;
        }
        const destName = projects.find(p => p.id === payload.dest_workspace_id)?.name || 'workspace';
        addToast(`Worker ${payload.mode === 'move' ? 'moved' : 'copied'} to ${destName}`);
        if (data.warnings?.length) {
          for (const w of data.warnings) addToast(w, 'error');
        }
      } catch (e) {
        addToast('Transfer failed: ' + e.message, 'error');
      }
      transferSlot.value = null;
    }
    function saveWorkerConfig({ slot, fields }) { socket.emit('worker:configure', _wsData({ slot, fields })); }

    // Execution actions
    function assignTask(taskId, slot) { socket.emit('task:assign', _wsData({ task_id: taskId, slot })); }
    function startWorkerSlot(slot) { socket.emit('worker:start', _wsData({ slot })); }
    function stopWorkerSlot(slot) { socket.emit('worker:stop', _wsData({ slot })); }

    // Focus tab management
    function openFocusTab(slotIndex) {
      const worker = state.layout?.slots?.[slotIndex];
      if (!worker) return;
      const existing = focusTabs.find(t => t.slotIndex === slotIndex);
      if (!existing) {
        focusTabs.push({ slotIndex, workspaceId: activeWorkspaceId.value, label: worker.name });
      }
      activeTab.value = 'focus-' + slotIndex;
      // Ensure reactive buffer and request catchup
      _ensureBuffer(slotIndex);
      socket.emit('worker:output:request', _wsData({ slot: slotIndex }));
    }
    function closeFocusTab(slotIndex) {
      const idx = focusTabs.findIndex(t => t.slotIndex === slotIndex);
      if (idx >= 0) focusTabs.splice(idx, 1);
      if (activeTab.value === 'focus-' + slotIndex) {
        activeTab.value = 'workers';
      }
      delete outputBuffers[slotIndex];
    }
    function focusTask(slotIndex) {
      const worker = state.layout?.slots?.[slotIndex];
      if (!worker?.task_queue?.length) return null;
      return state.tasks.find(t => t.id === worker.task_queue[0]) || null;
    }

    function tabIcon(tab) {
      if (tab.isFocus) return 'terminal';
      if (tab.isChat) return 'message-square';
      return ({
        tasks: 'tag',
        workers: 'bot',
        files: 'folder',
        commits: 'git-commit',
      })[tab.id] || 'circle';
    }

    const allTabs = computed(() => {
      const activeWorkerCount = (state.layout?.slots || []).filter(s => s?.state === 'working').length;
      const workersLabel = activeWorkerCount > 0 ? `Workers (${activeWorkerCount})` : 'Workers';
      const tabs = [
        { id: 'tasks', label: 'Tickets', icon: 'tag' },
        { id: 'workers', label: workersLabel, icon: 'bot' },
        { id: 'files', label: 'Files', icon: 'folder' },
        { id: 'commits', label: 'Commits', icon: 'git-commit' },
      ];
      for (const ct of chatTabs) {
        tabs.push({ id: ct.id, label: ct.label, isChat: true, canClose: chatTabs.length > 1, icon: 'message-square' });
      }
      for (const ft of focusTabs) {
        tabs.push({ id: 'focus-' + ft.slotIndex, label: ft.label, isFocus: true, slotIndex: ft.slotIndex, icon: 'terminal' });
      }
      return tabs;
    });

    // Config/team actions
    function updateConfig(data) { socket.emit('config:update', _wsData(data)); }
    function saveColumns({ columns, ticketMigrations }) {
      updateConfig({ columns });
      for (const { fromKey, toKey } of (ticketMigrations || [])) {
        const affected = state.tasks.filter(t => t.status === fromKey);
        for (const task of affected) {
          updateTask({ id: task.id, status: toKey });
        }
      }
      showColumnManager.value = false;
    }
    function saveTeam(name) { socket.emit('team:save', _wsData({ name })); }
    function loadTeam(name) { socket.emit('team:load', _wsData({ name })); }
    function saveProfile(data) { socket.emit('profile:create', _wsData(data)); }

    // Project actions
    function addProject(path) { socket.emit('project:add', { path }); }
    function newProject(path) { socket.emit('project:new', { path }); }
    function cloneProject(data) { socket.emit('project:clone', data); }
    function removeProject(wsId) { socket.emit('project:remove', { workspaceId: wsId }); }

    function toggleLeftPane() { leftPaneVisible.value = !leftPaneVisible.value; }

    function _downloadNameFromDisposition(contentDisposition, fallback) {
      if (typeof contentDisposition !== 'string' || !contentDisposition) return fallback;
      const match = contentDisposition.match(/filename\*?=(?:UTF-8''|\"?)([^\";]+)/i);
      if (!match || !match[1]) return fallback;
      try {
        return decodeURIComponent(match[1].trim());
      } catch (_err) {
        return match[1].trim();
      }
    }

    async function _downloadZip(url, fallbackName) {
      const resp = await fetch(url, { method: 'GET' });
      if (!resp.ok) {
        let message = 'Download failed';
        try {
          const body = await resp.json();
          if (body && body.error) message = body.error;
        } catch (_err) {
          // Keep generic message when non-JSON response body.
        }
        throw new Error(message);
      }
      const blob = await resp.blob();
      const name = _downloadNameFromDisposition(resp.headers.get('content-disposition'), fallbackName);
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = name || fallbackName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    }

    async function exportWorkspace() {
      if (!activeWorkspaceId.value) return;
      try {
        const url = `/api/export/workspace?workspaceId=${encodeURIComponent(activeWorkspaceId.value)}`;
        await _downloadZip(url, 'bullpen-workspace.zip');
        addToast('Workspace export ready');
      } catch (e) {
        addToast('Workspace export failed: ' + e.message, 'error');
      }
    }

    async function exportAll() {
      try {
        await _downloadZip('/api/export/all', 'bullpen-all.zip');
        addToast('All-workspace export ready');
      } catch (e) {
        addToast('Export all failed: ' + e.message, 'error');
      }
    }

    async function _importZip(url, file, successMessage) {
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      const resp = await fetch(url, { method: 'POST', body: form });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(body?.error || 'Import failed');
      }
      addToast(successMessage + (body?.imported ? ` (${body.imported})` : ''));
    }

    async function importWorkspace(file) {
      if (!activeWorkspaceId.value) return;
      try {
        const url = `/api/import/workspace?workspaceId=${encodeURIComponent(activeWorkspaceId.value)}`;
        await _importZip(url, file, 'Workspace import complete');
      } catch (e) {
        addToast('Workspace import failed: ' + e.message, 'error');
      }
    }

    async function importAll(file) {
      try {
        await _importZip('/api/import/all', file, 'All-workspace import complete');
      } catch (e) {
        addToast('Import all failed: ' + e.message, 'error');
      }
    }

    // Theme
    function setTheme(themeId) {
      const next = _normalizeTheme(themeId);
      _applyTheme(next);
      if (activeWorkspaceId.value) {
        const ws = _getWs(activeWorkspaceId.value);
        ws.config = { ...(ws.config || {}), theme: next };
        if (_isActive(activeWorkspaceId.value)) state.config = ws.config;
        updateConfig({ theme: next });
      }
    }
    function setAmbientPreset(preset) {
      const next = _normalizeAmbientPreset(preset);
      if (!activeWorkspaceId.value) return;
      const ws = _getWs(activeWorkspaceId.value);
      ws.config = { ...(ws.config || {}), ambient_preset: next };
      if (_isActive(activeWorkspaceId.value)) {
        state.config = ws.config;
        _applyWorkspaceAmbient(activeWorkspaceId.value);
      }
      updateConfig({ ambient_preset: next });
    }
    function setAmbientVolume(volume) {
      const next = _normalizeAmbientVolume(volume);
      if (!activeWorkspaceId.value) return;
      const ws = _getWs(activeWorkspaceId.value);
      ws.config = { ...(ws.config || {}), ambient_volume: next };
      if (_isActive(activeWorkspaceId.value)) {
        state.config = ws.config;
        _applyWorkspaceAmbient(activeWorkspaceId.value);
      }
      updateConfig({ ambient_volume: next });
    }
    const themeOptions = computed(() => THEME_CATALOG.map(t => ({ id: t.id, label: t.label })));
    const currentTheme = computed(() => _normalizeTheme(state.config?.theme || 'dark'));
    const ambientPresets = computed(() => AMBIENT_PRESETS);
    const currentAmbientPreset = computed(() => _normalizeAmbientPreset(state.config?.ambient_preset) || '');
    const currentAmbientVolume = computed(() => _normalizeAmbientVolume(state.config?.ambient_volume));
    const activeProjectName = computed(() => _workspaceBaseName(state.workspace));
    const visibleTicketTasks = computed(() => {
      if (ticketsViewMode.value === 'list' && ticketListScope.value === 'archived') {
        const ws = activeWorkspaceId.value ? _getWs(activeWorkspaceId.value) : null;
        return ws?.archivedTasks || [];
      }
      return state.tasks;
    });

    function addToast(message, type = 'info') {
      const id = ++toastId;
      toasts.push({ id, message, type });
      // Cap at 5 visible
      while (toasts.length > 5) toasts.shift();
      if (type !== 'error') {
        setTimeout(() => {
          const idx = toasts.findIndex(t => t.id === id);
          if (idx >= 0) toasts.splice(idx, 1);
        }, 5000);
      }
    }

    function dismissToast(id) {
      const idx = toasts.findIndex(t => t.id === id);
      if (idx >= 0) toasts.splice(idx, 1);
    }

    // Grid options for tab bar selector
    const multipleWorkspaces = computed(() => projects.length >= 2);

    const gridOptions = computed(() => {
      const opts = [];
      for (let r = 2; r <= 7; r++) {
        for (let c = 2; c <= 10; c++) {
          opts.push(`${r}x${c}`);
        }
      }
      return opts;
    });

    function onTabBarGridResize(e) {
      const [rows, cols] = e.target.value.split('x').map(Number);
      const layout = state.layout;
      const slots = layout?.slots || [];
      let maxOccupied = -1;
      for (let i = 0; i < slots.length; i++) {
        if (slots[i]) maxOccupied = i;
      }
      const newTotal = rows * cols;
      if (maxOccupied >= newTotal) {
        alert(`Cannot resize: worker in slot ${maxOccupied + 1} would be displaced. Move or remove workers first.`);
        const curRows = state.config.grid?.rows || 4;
        const curCols = state.config.grid?.cols || 6;
        e.target.value = curRows + 'x' + curCols;
        return;
      }
      updateConfig({ grid: { rows, cols } });
    }

    return {
      state, workspaces, activeWorkspaceId, switchWorkspace, projects,
      addProject, newProject, cloneProject, removeProject,
      connected, activeTab, leftPaneVisible, toasts, quickCreateClearToken,
      showCreateModal, showColumnManager, selectedTask, configureSlot, configureWorkerData,
      toggleLeftPane, setTheme, setAmbientPreset, setAmbientVolume, themeOptions, currentTheme, ambientPresets, currentAmbientPreset, currentAmbientVolume, createTask, quickCreateTask, updateTask, deleteTask, archiveTask, archiveDone, clearTaskOutput,
      moveTask, selectTask, addWorker, removeWorker, moveWorker,
      saveWorkerConfig, assignTask, startWorkerSlot,
      stopWorkerSlot, updateConfig, saveColumns, saveTeam, loadTeam, saveProfile, addToast, dismissToast,
      gridOptions, onTabBarGridResize, duplicateWorker, multipleWorkspaces,
      transferSlot, transferMode, openTransfer, transferWorker,
      outputBuffers, focusTabs, openFocusTab, closeFocusTab, focusTask, allTabs,
      ticketsViewMode, ticketListScope, setTicketListScope, visibleTicketTasks, chatTabs, addLiveAgentTab, closeLiveAgentTab,
      tabIcon, activeProjectName, exportWorkspace, exportAll, importWorkspace, importAll,
    };
  },
  mounted() {
    const unlockAudio = () => {
      if (window.ambientAudio) window.ambientAudio.unlock();
      window.removeEventListener('pointerdown', unlockAudio);
      window.removeEventListener('keydown', unlockAudio);
      window.removeEventListener('touchstart', unlockAudio);
    };
    window.addEventListener('pointerdown', unlockAudio, { once: true });
    window.addEventListener('keydown', unlockAudio, { once: true });
    window.addEventListener('touchstart', unlockAudio, { once: true });

    renderLucideIcons(this.$el);
  },
  updated() {
    renderLucideIcons(this.$el);
  },
  template: `
    <div class="app-container">
      <TopToolbar
        :project-name="activeProjectName"
        :connected="connected"
        :themes="themeOptions"
        :active-theme="currentTheme"
        :ambient-presets="ambientPresets"
        :ambient-preset="currentAmbientPreset"
        :ambient-volume="currentAmbientVolume"
        @toggle-left-pane="toggleLeftPane"
        @export-workspace="exportWorkspace"
        @export-all="exportAll"
        @import-workspace="importWorkspace"
        @import-all="importAll"
        @set-theme="setTheme"
        @set-ambient-preset="setAmbientPreset"
        @set-ambient-volume="setAmbientVolume"
      />
      <div class="app-body">
        <LeftPane
          :tasks="state.tasks"
          :layout="state.layout"
          :config="state.config"
          :visible="leftPaneVisible"
          :projects="projects"
          :active-workspace-id="activeWorkspaceId"
          :workspaces="workspaces"
          :quick-create-clear-token="quickCreateClearToken"
          @new-task="showCreateModal = true"
          @quick-create-task="quickCreateTask"
          @select-task="selectTask"
          @switch-workspace="switchWorkspace"
          @add-project="addProject"
          @new-project="newProject"
          @clone-project="cloneProject"
          @remove-project="removeProject"
        />
        <div class="main-pane">
          <div class="tab-bar">
            <div class="tab-bar-left">
              <button
                v-for="tab in allTabs"
                :key="tab.id"
                class="tab-btn"
                :class="{ active: activeTab === tab.id, 'focus-tab': tab.isFocus }"
                @click="activeTab = tab.id"
              >
                <span class="tab-btn-label">
                  <i class="tab-label-icon" :data-lucide="tab.icon || tabIcon(tab)" aria-hidden="true"></i>
                  <span v-if="tab.isFocus" class="focus-dot"></span>
                  <span class="tab-label-text">{{ tab.label }}</span>
                </span>
                <span v-if="tab.isFocus" class="tab-close" @click.stop="closeFocusTab(tab.slotIndex)">&times;</span>
                <span v-if="tab.isChat && tab.canClose" class="tab-close" @click.stop="closeLiveAgentTab(tab.id)">&times;</span>
              </button>
              <button class="tab-btn tab-btn-add" @click="addLiveAgentTab" title="Add Live Agent tab">+</button>
            </div>
            <div v-if="activeTab === 'tasks'" class="tab-bar-right">
              <button class="btn btn-sm" @click="showColumnManager = true" title="Add, remove, or reorder columns">Columns</button>
              <div class="view-mode-selector">
                <button class="btn-icon view-mode-btn" :class="{ active: ticketsViewMode === 'kanban' }" @click="ticketsViewMode = 'kanban'" title="Kanban view">&#10697;</button>
                <button class="btn-icon view-mode-btn" :class="{ active: ticketsViewMode === 'list' }" @click="ticketsViewMode = 'list'" title="List view">&#9776;</button>
              </div>
            </div>
            <div v-if="activeTab === 'workers'" class="tab-bar-right">
              <span class="bullpen-path" :title="state.workspace">{{ state.workspace ? state.workspace.split('/').slice(-2).join('/') : '' }}</span>
              <select class="form-select" :value="(state.config.grid?.rows || 4) + 'x' + (state.config.grid?.cols || 6)" @change="onTabBarGridResize">
                <option v-for="opt in gridOptions" :key="opt" :value="opt">{{ opt }}</option>
              </select>
            </div>
          </div>
          <div class="tab-content">
            <KanbanTab
              v-if="activeTab === 'tasks'"
              :tasks="visibleTicketTasks"
              :columns="state.config.columns"
              :layout="state.layout"
              :view-mode="ticketsViewMode"
              :list-scope="ticketListScope"
              @select-task="selectTask"
              @move-task="moveTask"
              @archive-done="archiveDone"
              @new-task="showCreateModal = true"
              @update-list-scope="setTicketListScope"
            />
            <BullpenTab
              v-if="activeTab === 'workers'"
              :layout="state.layout"
              :config="state.config"
              :profiles="state.profiles"
              :tasks="state.tasks"
              :workspace="state.workspace"
              :multiple-workspaces="multipleWorkspaces"
              @add-worker="addWorker"
              @configure-worker="configureSlot = $event"
              @select-task="selectTask"
              @open-focus="openFocusTab"
              @transfer-worker="openTransfer"
            />
            <FilesTab v-if="activeTab === 'files'" :files-version="state.filesVersion" :workspace-id="activeWorkspaceId" :key="'files-' + (activeWorkspaceId || 'none')" />
            <CommitsTab
              v-if="activeTab === 'commits'"
              :workspace-id="activeWorkspaceId"
              :key="'commits-' + (activeWorkspaceId || 'none')"
            />
            <LiveAgentChatTab
              v-for="ct in chatTabs"
              v-show="activeTab === ct.id"
              :key="ct.id"
              :session-id="ct.sessionId"
            />
            <WorkerFocusView
              v-for="ft in focusTabs"
              v-show="activeTab === 'focus-' + ft.slotIndex"
              :key="'focus-' + ft.slotIndex"
              :worker="state.layout?.slots?.[ft.slotIndex]"
              :slot-index="ft.slotIndex"
              :task="focusTask(ft.slotIndex)"
              :output-lines="outputBuffers[ft.slotIndex]"
              @stop="stopWorkerSlot(ft.slotIndex)"
              @close="closeFocusTab(ft.slotIndex)"
            />
          </div>
        </div>
        <TaskDetailPanel
          :task="selectedTask"
          :columns="state.config.columns"
          @close="selectTask(null)"
          @update="updateTask"
          @delete="deleteTask"
          @archive="archiveTask"
          @clear-output="clearTaskOutput"
          @toast="addToast"
        />
      </div>
      <TaskCreateModal
        :visible="showCreateModal"
        @close="showCreateModal = false"
        @create="createTask"
      />
      <WorkerConfigModal
        :worker="configureWorkerData"
        :slot-index="configureSlot"
        :columns="state.config.columns"
        :workers="state.layout.slots"
        @close="configureSlot = null"
        @save="saveWorkerConfig"
        @remove="removeWorker"
        @save-profile="saveProfile"
      />
      <WorkerTransferModal
        :visible="transferSlot !== null"
        :worker="transferSlot !== null ? state.layout.slots?.[transferSlot] : null"
        :slot-index="transferSlot"
        :mode="transferMode"
        :projects="projects"
        :active-workspace-id="activeWorkspaceId"
        @close="transferSlot = null"
        @transfer="transferWorker"
      />
      <ColumnManagerModal
        :visible="showColumnManager"
        :columns="state.config.columns"
        :tasks="state.tasks"
        @close="showColumnManager = false"
        @save="saveColumns"
      />
      <ToastContainer :toasts="toasts" @dismiss="dismissToast" />
    </div>
  `
});

app.mount('#app');
