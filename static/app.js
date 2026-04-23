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
      { id: 'eyeshade', label: 'Eyeshade', mode: 'light' },
      { id: 'eyeshade-dark', label: 'Eyeshade Dark', mode: 'dark' },
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
      config: { name: 'Bullpen', grid: { layout: 'medium', columnWidth: 220, viewportOrigin: { col: 0, row: 0 } }, columns: [], ambient_preset: null, ambient_volume: 40 },
      layout: { slots: [] },
      tasks: [],
      profiles: [],
      teams: [],
      filesVersion: 0,
    });

    const activeWorkspaceId = ref(null);
    const bullpenTabRef = ref(null);
    const projects = reactive([]);  // [{id, name, available}]
    const projectsLoaded = ref(false);  // true once server has delivered initial projects:updated

    function _defaultWsData() {
      return {
        workspace: '',
        config: { name: 'Bullpen', grid: { layout: 'medium', columnWidth: 220, viewportOrigin: { col: 0, row: 0 } }, columns: [], ambient_preset: null, ambient_volume: 40 },
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
      const grid = safe.grid || {};
      const rawColumnWidth = Number(grid.columnWidth);
      const columnWidth = Number.isFinite(rawColumnWidth) ? rawColumnWidth : 220;
      const rawRowHeight = Number(grid.rowHeight);
      const rowHeight = Number.isFinite(rawRowHeight)
        ? Math.max(32, Math.min(480, Math.round(rawRowHeight)))
        : undefined;
      safe.grid = {
        columnWidth: Math.max(140, Math.min(480, Math.round(columnWidth / 20) * 20)),
        rowHeight,
        viewportOrigin: {
          col: Number.isFinite(Number(grid.viewportOrigin?.col)) ? Number(grid.viewportOrigin.col) : 0,
          row: Number.isFinite(Number(grid.viewportOrigin?.row)) ? Number(grid.viewportOrigin.row) : 0,
        },
        // Legacy values are kept so old layouts can be migrated client/server side.
        rows: Number.isFinite(Number(grid.rows)) ? Number(grid.rows) : undefined,
        cols: Number.isFinite(Number(grid.cols)) ? Number(grid.cols) : undefined,
      };
      safe.theme = _normalizeTheme(safe.theme || 'dark');
      safe.ambient_preset = _normalizeAmbientPreset(safe.ambient_preset);
      safe.ambient_volume = _normalizeAmbientVolume(safe.ambient_volume);
      safe.provider_colors = _normalizeProviderColors(safe.provider_colors);
      return safe;
    }

    const HEX_COLOR_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
    function _normalizeProviderColors(value) {
      const defaults = window.DEFAULT_AGENT_COLORS || {};
      const result = { ...defaults };
      if (value && typeof value === 'object') {
        for (const agent of Object.keys(defaults)) {
          const v = value[agent];
          if (typeof v === 'string' && HEX_COLOR_RE.test(v)) result[agent] = v.toLowerCase();
        }
      }
      return result;
    }

    function _applyWorkspaceProviderColors(wsId) {
      const ws = workspaces[wsId];
      const colors = _normalizeProviderColors(ws?.config?.provider_colors);
      if (window.BULLPEN_AGENT_COLORS) {
        window.BULLPEN_AGENT_COLORS.overrides = colors;
      }
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
    const PRISM_DARK_INTEGRITY = 'sha384-wFjoQjtV1y5jVHbt0p35Ui8aV8GVpEZkyF99OXWqP/eNJDU93D3Ugxkoyh6Y2I4A';
    const PRISM_LIGHT_INTEGRITY = 'sha384-rCCjoCPCsizaAAYVoz1Q0CmCTvnctK0JkfCSjx7IIxexTBg+uCKtFYycedUjMyA2';
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
      if (prismLink) {
        const isLight = _themeMode(next) === 'light';
        const nextHref = isLight ? PRISM_LIGHT : PRISM_DARK;
        const nextIntegrity = isLight ? PRISM_LIGHT_INTEGRITY : PRISM_DARK_INTEGRITY;
        if (prismLink.href !== nextHref) {
          const replacement = document.createElement('link');
          replacement.id = 'prism-theme';
          replacement.rel = 'stylesheet';
          replacement.integrity = nextIntegrity;
          replacement.crossOrigin = 'anonymous';
          replacement.href = nextHref;
          prismLink.parentNode.replaceChild(replacement, prismLink);
        }
      }
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
      if (!wsId) return;
      // Accept switches to workspaces the client has not yet joined. The server
      // scopes state:init to joined rooms, so the local workspaces dict starts
      // out only containing the initial workspace — guard against unknown ids
      // by checking the project list, then lazily init so downstream access has
      // a default entry until state:init arrives from the project:join below.
      if (!workspaces[wsId] && !projects.some(p => p.id === wsId)) return;
      _getWs(wsId);
      const currentChatTab = chatTabs.find(t => t.id === activeTab.value);
      if (currentChatTab?.workspaceId) {
        lastLiveAgentTabByWorkspace[currentChatTab.workspaceId] = currentChatTab.id;
      }
      const wasLiveAgent = !!currentChatTab;
      activeWorkspaceId.value = wsId;
      workspaces[wsId].unseenActivity = 0;
      ticketListScope.value = 'live';
      // Join the workspace room before emitting any workspace-scoped events
      // (e.g. chat:tab:open from _ensureChatTabForWorkspace). The server
      // rejects workspace-scoped events from clients not yet in the room.
      if (socket?.connected) socket.emit('project:join', { workspaceId: wsId });
      const ensuredChatTab = _ensureChatTabForWorkspace(wsId);
      _syncToView(wsId);
      _applyWorkspaceTheme(wsId);
      _applyWorkspaceAmbient(wsId);
      _applyWorkspaceProviderColors(wsId);
      _updateDocumentTitle();
      if (wasLiveAgent) {
        const preferred = chatTabs.find(t => t.id === lastLiveAgentTabByWorkspace[wsId] && t.workspaceId === wsId);
        const fallback = preferred || ensuredChatTab || chatTabs.find(t => t.workspaceId === wsId);
        if (fallback) {
          setActiveTab(fallback.id);
        } else {
          activeTab.value = 'tasks';
        }
        return;
      }
      // If active tab belongs to a different workspace, fall back to tasks
      const ct = chatTabs.find(t => t.id === activeTab.value);
      if (ct && ct.workspaceId && ct.workspaceId !== wsId) { activeTab.value = 'tasks'; return; }
      const ft = focusTabs.find(t => 'focus-' + t.slotIndex === activeTab.value);
      if (ft && ft.workspaceId && ft.workspaceId !== wsId) activeTab.value = 'tasks';
    }

    const connected = ref(false);
    const activeTab = ref('tasks');
    const requestedCommitDiffHash = ref('');
    const ticketsViewMode = ref('kanban');
    const ticketListScope = ref('live');
    const leftPaneVisible = ref(true);
    const toasts = reactive([]);
    const showCreateModal = ref(false);
    const showColumnManager = ref(false);
    const selectedTaskId = ref(null);
    const selectedTaskMode = ref('edit'); // 'edit' | 'read'
    const configureSlot = ref(null);
    const transferSlot = ref(null);
    const transferMode = ref('copy');
    const quickCreateClearToken = ref(0);
    const pendingQuickCreates = reactive([]);

    // Worker Focus Mode state
    const outputBuffers = reactive({});  // keyed by workspaceId + slot index
    const outputBufferMeta = reactive({});
    const focusTabs = reactive([]);      // [{slotIndex, workspaceId, label}]
    const chatTabs = reactive([]);
    const lastLiveAgentTabByWorkspace = reactive({});
    let taskDragActive = false;
    const deferredTaskUpdates = new Map();
    let toastId = 0;

    function _taskUpdateKey(wsId, taskId) {
      return `${wsId || ''}:${taskId || ''}`;
    }

    function _sameTaskExceptTokens(current, next) {
      if (!current || !next) return false;
      const keys = new Set([...Object.keys(current), ...Object.keys(next)]);
      keys.delete('tokens');
      for (const key of keys) {
        if (JSON.stringify(current[key]) !== JSON.stringify(next[key])) return false;
      }
      return true;
    }

    function _applyTaskUpdateToWorkspace(ws, task) {
      const idx = ws.tasks.findIndex(t => t.id === task.id);
      if (idx >= 0) ws.tasks[idx] = task;
      else ws.tasks.push(task);
    }

    function _flushDeferredTaskUpdates() {
      if (!deferredTaskUpdates.size) return;
      for (const task of deferredTaskUpdates.values()) {
        const wsId = task.workspaceId || activeWorkspaceId.value;
        const ws = _getWs(wsId);
        _applyTaskUpdateToWorkspace(ws, task);
      }
      deferredTaskUpdates.clear();
    }

    window.addEventListener('bullpen:task-drag:start', () => {
      taskDragActive = true;
    });
    window.addEventListener('bullpen:task-drag:end', () => {
      taskDragActive = false;
      _flushDeferredTaskUpdates();
    });

    function _newChatSessionId() {
      return 'chat-' + crypto.randomUUID();
    }

    function _defaultChatSessionId(wsId) {
      return `chat-default-${wsId}`;
    }

    function _normalizeChatTab(tab, wsId) {
      const sessionId = String(tab?.sessionId || '').trim();
      if (!sessionId) return null;
      const id = String(tab?.id || sessionId).trim() || sessionId;
      const label = String(tab?.label || 'Live Agent').trim() || 'Live Agent';
      return { id, label, sessionId, workspaceId: wsId };
    }

    function _upsertChatTab(rawTab, { activate = false } = {}) {
      const wsId = rawTab?.workspaceId;
      const normalized = _normalizeChatTab(rawTab, wsId);
      if (!normalized) return null;
      const existing = chatTabs.find(t => t.workspaceId === wsId && t.sessionId === normalized.sessionId);
      if (existing) {
        existing.id = normalized.id;
        existing.label = normalized.label;
        if (activate) setActiveTab(existing.id);
        return existing;
      }
      chatTabs.push(normalized);
      if (activate) setActiveTab(normalized.id);
      return normalized;
    }

    function _rememberLiveAgentTab(tabId) {
      const tab = chatTabs.find(t => t.id === tabId);
      if (tab?.workspaceId) lastLiveAgentTabByWorkspace[tab.workspaceId] = tab.id;
    }

    function setActiveTab(tabId) {
      activeTab.value = tabId;
      _rememberLiveAgentTab(tabId);
    }

    function focusWorkerGridSoon() {
      if (activeTab.value === 'workers') {
        Vue.nextTick(() => bullpenTabRef.value?.focusViewport?.());
      }
    }

    function addLiveAgentTab({ activate = true } = {}) {
      const wsId = activeWorkspaceId.value;
      if (!wsId) return null;  // chat tabs are strictly per-workspace
      const existingTabs = chatTabs.filter(t => t.workspaceId === wsId);
      const shouldSeedDefault = !activate && existingTabs.length === 0;
      const sessionId = shouldSeedDefault ? _defaultChatSessionId(wsId) : _newChatSessionId();
      const projectName = _workspaceBaseName(workspaces[wsId]?.workspace || '');
      const perWsCount = existingTabs.length + 1;
      const suffix = perWsCount === 1 ? '' : ` ${perWsCount}`;
      const tab = _upsertChatTab({
        id: sessionId,
        label: projectName ? `Live Agent${suffix} (${projectName})` : `Live Agent${suffix}`,
        sessionId,
        workspaceId: wsId,
      }, { activate });
      if (socket?.connected && tab) {
        socket.emit('chat:tab:open', {
          workspaceId: wsId,
          id: tab.id,
          sessionId: tab.sessionId,
          label: tab.label,
        });
      }
      return tab;
    }

    function closeLiveAgentTab(tabId) {
      const idx = chatTabs.findIndex(t => t.id === tabId);
      if (idx < 0) return;
      const wsId = chatTabs[idx].workspaceId;
      const siblingCount = chatTabs.filter(t => t.workspaceId === wsId).length;
      if (siblingCount <= 1) return;  // keep at least one chat tab per workspace
      const closedSessionId = chatTabs[idx].sessionId;
      chatTabs.splice(idx, 1);
      if (socket?.connected) socket.emit('chat:tab:close', { workspaceId: wsId, sessionId: closedSessionId });
      if (lastLiveAgentTabByWorkspace[wsId] === tabId) {
        const fallback = chatTabs.find(t => t.workspaceId === wsId);
        if (fallback) lastLiveAgentTabByWorkspace[wsId] = fallback.id;
        else delete lastLiveAgentTabByWorkspace[wsId];
      }
      if (activeTab.value === tabId) {
        const fallback = chatTabs.find(t => t.workspaceId === wsId);
        if (fallback) setActiveTab(fallback.id);
        else activeTab.value = 'tasks';
      }
    }

    function _ensureChatTabForWorkspace(wsId) {
      if (!wsId) return null;
      const existing = chatTabs.find(t => t.workspaceId === wsId);
      if (existing) return existing;
      return addLiveAgentTab({ activate: false });
    }

    const selectedTask = computed(() => {
      if (!selectedTaskId.value) return null;
      const liveTask = state.tasks.find(t => t.id === selectedTaskId.value);
      if (liveTask) return liveTask;
      if (!activeWorkspaceId.value) return null;
      const archived = _getWs(activeWorkspaceId.value).archivedTasks || [];
      return archived.find(t => t.id === selectedTaskId.value) || null;
    });

    const selectedTaskReadOnly = computed(() => {
      if (!selectedTask.value) return false;
      if (selectedTaskMode.value === 'read') return true;
      return !state.tasks.some(t => t.id === selectedTask.value.id);
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

    if (window.EventSounds) window.EventSounds.init(socket);

    let hasConnectedOnce = false;
    let disconnectToastId = null;
    socket.on('connect', () => {
      const wasDisconnected = hasConnectedOnce && !connected.value;
      connected.value = true;
      if (disconnectToastId != null) {
        dismissToast(disconnectToastId);
        disconnectToastId = null;
      }
      if (wasDisconnected) addToast('Reconnected to Bullpen server');
      hasConnectedOnce = true;
    });
    socket.on('disconnect', () => {
      const wasConnected = connected.value;
      connected.value = false;
      if (wasConnected) {
        disconnectToastId = addToast('Disconnected from Bullpen server. Changes are paused until connection is restored.', 'error');
      }
    });
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
        _applyWorkspaceProviderColors(wsId);
        _updateDocumentTitle();
      }
      socket.emit('chat:tabs:request', { workspaceId: wsId });
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
      const current = ws.tasks.find(t => t.id === task.id);
      if (taskDragActive && current && _sameTaskExceptTokens(current, task)) {
        deferredTaskUpdates.set(_taskUpdateKey(wsId, task.id), task);
        return;
      }
      _applyTaskUpdateToWorkspace(ws, task);
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
      if (selectedTaskId.value === data.id) {
        selectedTaskId.value = null;
        selectedTaskMode.value = 'edit';
      }
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
        _applyWorkspaceProviderColors(wsId);
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
    socket.on('error', (data) => { addToast((data && data.message) || 'An error occurred', 'error'); });
    socket.on('projects:updated', (list) => {
      projects.splice(0, projects.length, ...list);
      projectsLoaded.value = true;
    });
    socket.on('project:removed', (data) => {
      const removedId = data.workspaceId;
      delete workspaces[removedId];
      for (let i = chatTabs.length - 1; i >= 0; i -= 1) {
        if (chatTabs[i].workspaceId === removedId) chatTabs.splice(i, 1);
      }
      delete lastLiveAgentTabByWorkspace[removedId];
      if (activeWorkspaceId.value === removedId) {
        // Switch to first available
        const firstId = projects.find(p => p.id !== removedId)?.id;
        if (firstId) switchWorkspace(firstId);
      }
    });
    socket.on('chat:tabs', (data) => {
      const wsId = data?.workspaceId || activeWorkspaceId.value;
      if (!wsId) return;
      const prevActiveTabId = activeTab.value;
      const prevActiveTab = chatTabs.find(t => t.id === prevActiveTabId);
      const activeWasChatInWorkspace = !!(prevActiveTab && prevActiveTab.workspaceId === wsId);
      const incoming = Array.isArray(data?.tabs) ? data.tabs : [];
      const normalized = incoming.map(tab => _normalizeChatTab(tab, wsId)).filter(Boolean);

      for (let i = chatTabs.length - 1; i >= 0; i -= 1) {
        if (chatTabs[i].workspaceId === wsId) chatTabs.splice(i, 1);
      }
      for (const tab of normalized) {
        chatTabs.push(tab);
      }

      if (!chatTabs.find(t => t.workspaceId === wsId)) {
        if (_isActive(wsId)) addLiveAgentTab({ activate: false });
        return;
      }

      if (!chatTabs.find(t => t.workspaceId === wsId && t.id === lastLiveAgentTabByWorkspace[wsId])) {
        const fallback = chatTabs.find(t => t.workspaceId === wsId);
        if (fallback) lastLiveAgentTabByWorkspace[wsId] = fallback.id;
      }

      if (activeWasChatInWorkspace && !chatTabs.find(t => t.workspaceId === wsId && t.id === prevActiveTabId)) {
        const preferred = chatTabs.find(t => t.id === lastLiveAgentTabByWorkspace[wsId] && t.workspaceId === wsId);
        const fallback = preferred || chatTabs.find(t => t.workspaceId === wsId);
        if (fallback) setActiveTab(fallback.id);
        else activeTab.value = 'tasks';
      }
    });
    socket.on('files:changed', (data) => {
      const wsId = (data && data.workspaceId) || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.filesVersion++;
      if (_isActive(wsId)) state.filesVersion = ws.filesVersion;
    });

    // Worker output streaming
    const OUTPUT_BUFFER_CAP = 5000;
    function _outputBufferKey(slot, workspaceId = activeWorkspaceId.value) {
      return `${workspaceId || 'default'}:${slot}`;
    }
    function _ensureBuffer(slot, workspaceId = activeWorkspaceId.value) {
      const key = _outputBufferKey(slot, workspaceId);
      if (!outputBuffers[key]) outputBuffers[key] = reactive([]);
      if (!outputBufferMeta[key]) {
        outputBufferMeta[key] = reactive({
          loaded: false,
          requestedAt: 0,
        });
      }
      return key;
    }
    function outputLinesForSlot(slot, workspaceId = activeWorkspaceId.value) {
      return outputBuffers[_outputBufferKey(slot, workspaceId)] || [];
    }
    function requestOutputCatchup(slot, options = {}) {
      const workspaceId = options.workspaceId || activeWorkspaceId.value;
      if (slot == null || !workspaceId) return;
      const key = _ensureBuffer(slot, workspaceId);
      const meta = outputBufferMeta[key];
      const now = Date.now();
      if (!options.force) {
        if (meta.loaded) return;
        if (meta.requestedAt && now - meta.requestedAt < 1500) return;
      }
      meta.requestedAt = now;
      if ((options.workerType || '').toLowerCase() === 'service') {
        socket.emit('service:tail', { workspaceId, slot });
      } else {
        socket.emit('worker:output:request', { workspaceId, slot });
      }
    }
    // Safe append: spreading a huge array into push() overflows V8's argument
    // stack (~100k–500k args). Trim to the cap first, then push one-by-one.
    function _appendLines(buf, incoming) {
      if (!incoming || !incoming.length) return;
      const tail = incoming.length > OUTPUT_BUFFER_CAP
        ? incoming.slice(-OUTPUT_BUFFER_CAP)
        : incoming;
      for (let i = 0; i < tail.length; i++) buf.push(tail[i]);
      if (buf.length > OUTPUT_BUFFER_CAP) {
        buf.splice(0, buf.length - OUTPUT_BUFFER_CAP);
      }
    }
    socket.on('worker:output', (data) => {
      const slot = data.slot;
      const wsId = data.workspaceId || activeWorkspaceId.value;
      const key = _ensureBuffer(slot, wsId);
      _appendLines(outputBuffers[key], data.lines);
      outputBufferMeta[key].loaded = true;
    });
    socket.on('worker:output:catchup', (data) => {
      const slot = data.slot;
      const wsId = data.workspaceId || activeWorkspaceId.value;
      const key = _ensureBuffer(slot, wsId);
      outputBuffers[key].length = 0;
      _appendLines(outputBuffers[key], data.lines || []);
      outputBufferMeta[key].loaded = true;
      outputBufferMeta[key].requestedAt = 0;
    });
    socket.on('worker:output:done', (data) => {
      const slot = data.slot;
      const wsId = data.workspaceId || activeWorkspaceId.value;
      const key = _ensureBuffer(slot, wsId);
      outputBuffers[key].length = 0;
      _appendLines(outputBuffers[key], data.lines || []);
      outputBufferMeta[key].loaded = true;
      outputBufferMeta[key].requestedAt = 0;
    });
    socket.on('service:state', (data) => {
      const wsId = data.workspaceId || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      const slot = Number(data.slot);
      const target = ws.layout?.slots?.[slot];
      if (target) {
        target.service_state = data;
        target.state = data.state || target.state;
        target.started_at = data.started_at || null;
      }
      if (!_isActive(wsId)) ws.unseenActivity++;
    });
    socket.on('service:log', (data) => {
      const slot = data.slot;
      const wsId = data.workspaceId || activeWorkspaceId.value;
      const key = _ensureBuffer(slot, wsId);
      if (data.reset) outputBuffers[key].length = 0;
      _appendLines(outputBuffers[key], data.lines || []);
      outputBufferMeta[key].loaded = true;
      outputBufferMeta[key].requestedAt = 0;
    });

    // Helper to attach workspaceId to outgoing events
    function _wsData(data) {
      return { ...data, workspaceId: activeWorkspaceId.value };
    }

    function emitSocketAction(eventName, data, { offlineMessage = 'Disconnected from Bullpen server. Changes are paused until connection is restored.' } = {}) {
      if (!socket?.connected) {
        addToast(offlineMessage, 'error');
        return false;
      }
      socket.emit(eventName, _wsData(data));
      return true;
    }

    // Task actions
    function createTask(data) {
      return emitSocketAction('task:create', data, {
        offlineMessage: 'Disconnected from Bullpen server. Ticket was not created.',
      });
    }
    function quickCreateTask(payload) {
      const title = typeof payload === 'string' ? payload.trim() : (payload?.title || '').trim();
      const description = typeof payload === 'string' ? '' : (payload?.description || '').trim();
      if (!title) return;
      const created = emitSocketAction('task:create', {
        title, type: 'task', priority: 'normal', tags: [], description,
      }, {
        offlineMessage: 'Disconnected from Bullpen server. Ticket was not created.',
      });
      if (created) pendingQuickCreates.push({ title, description });
    }
    function updateTask(data) {
      return emitSocketAction('task:update', data, {
        offlineMessage: 'Disconnected from Bullpen server. Ticket changes were not saved.',
      });
    }
    function deleteTask(id) {
      const task = state.tasks.find(t => t.id === id);
      if (task && (task.status === 'assigned' || task.status === 'in-progress')) {
        if (!confirm(`Task "${task.title}" is ${task.status}. Delete anyway?`)) return;
      }
      return emitSocketAction('task:delete', { id }, {
        offlineMessage: 'Disconnected from Bullpen server. Ticket was not deleted.',
      });
    }
    function archiveTask(id) {
      return emitSocketAction('task:archive', { id }, {
        offlineMessage: 'Disconnected from Bullpen server. Ticket was not archived.',
      });
    }
    function archiveDone() {
      const count = state.tasks.filter(t => t.status === 'done').length;
      if (count && confirm(`Archive ${count} done task(s)?`)) {
        return emitSocketAction('task:archive-done', {}, {
          offlineMessage: 'Disconnected from Bullpen server. Done tickets were not archived.',
        });
      }
    }
    function clearTaskOutput(id) {
      return emitSocketAction('task:clear_output', { id }, {
        offlineMessage: 'Disconnected from Bullpen server. Ticket output was not cleared.',
      });
    }
    function moveTask({ id, status }) {
      return emitSocketAction('task:update', { id, status }, {
        offlineMessage: 'Disconnected from Bullpen server. Ticket move was not saved.',
      });
    }
    function selectTask(payload, options = {}) {
      if (!payload) {
        selectedTaskId.value = null;
        selectedTaskMode.value = 'edit';
        return;
      }
      if (typeof payload === 'object') {
        selectedTaskId.value = payload.id || null;
        selectedTaskMode.value = payload.readOnly ? 'read' : 'edit';
        return;
      }
      selectedTaskId.value = payload;
      selectedTaskMode.value = options.readOnly ? 'read' : 'edit';
    }

    function setTicketListScope(scope) {
      const normalized = String(scope || '').trim().toLowerCase() === 'archived' ? 'archived' : 'live';
      ticketListScope.value = normalized;
      if (normalized === 'archived') {
        socket.emit('task:list', _wsData({ scope: 'archived' }));
      } else if (selectedTaskId.value) {
        const isLiveTaskSelected = state.tasks.some(t => t.id === selectedTaskId.value);
        if (!isLiveTaskSelected) {
          selectedTaskId.value = null;
          selectedTaskMode.value = 'edit';
        }
      }
    }

    // Worker actions
    function addWorker({ slot, coord, profile, type, fields }) {
      socket.emit('worker:add', _wsData({ slot, coord, profile, type, fields }));
    }
    function removeWorker(slot) {
      const worker = state.layout?.slots?.[slot];
      const name = worker?.name || `Slot ${slot + 1}`;
      const queued = Number(worker?.task_queue?.length || 0);
      const confirmMessage = queued > 0
        ? `Delete worker "${name}"?\n\nThis worker has ${queued} queued task(s).`
        : `Delete worker "${name}"?`;
      if (!confirm(confirmMessage)) return;
      socket.emit('worker:remove', _wsData({ slot }));
    }
    function moveWorker(from, to) {
      const payload = { from };
      if (to && typeof to === 'object') payload.to_coord = to;
      else payload.to = to;
      socket.emit('worker:move', _wsData(payload));
    }
    function moveWorkerGroup(moves) {
      socket.emit('worker:move_group', _wsData({ moves }));
    }
    function pasteWorkerConfig({ coord, worker, replace }) { socket.emit('worker:paste', _wsData({ coord, worker, replace: !!replace })); }
    function pasteWorkerGroup(items) {
      socket.emit('worker:paste_group', _wsData({ items }));
    }
    function duplicateWorker(slot) { socket.emit('worker:duplicate', _wsData({ slot })); }
    function openTransfer({ slot, mode }) {
      transferSlot.value = slot;
      transferMode.value = mode;
    }
    function closeCreateModal() {
      showCreateModal.value = false;
      focusWorkerGridSoon();
    }
    function closeColumnManager() {
      showColumnManager.value = false;
      focusWorkerGridSoon();
    }
    function closeWorkerConfig() {
      configureSlot.value = null;
      focusWorkerGridSoon();
    }
    function closeTransferModal() {
      transferSlot.value = null;
      focusWorkerGridSoon();
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
      closeTransferModal();
    }
    function saveWorkerConfig({ slot, fields }) { socket.emit('worker:configure', _wsData({ slot, fields })); }

    // Execution actions
    function assignTask(taskId, slot) { socket.emit('task:assign', _wsData({ task_id: taskId, slot })); }
    function _workerAt(slot) {
      return state.layout?.slots?.[slot] || null;
    }
    function startWorkerSlot(slot) {
      const worker = _workerAt(slot);
      socket.emit(worker?.type === 'service' ? 'service:start' : 'worker:start', _wsData({ slot }));
    }
    function stopWorkerSlot(slot) {
      const worker = _workerAt(slot);
      socket.emit(worker?.type === 'service' ? 'service:stop' : 'worker:stop', _wsData({ slot }));
    }
    function restartServiceSlot(slot) {
      socket.emit('service:restart', _wsData({ slot }));
    }
    function openServiceSite(slot) {
      const worker = _workerAt(slot);
      const url = window.getServiceSiteUrl ? window.getServiceSiteUrl(worker, window.location) : '';
      if (!url) {
        addToast('Service site is unavailable until this worker has a valid port', 'error');
        return;
      }
      const link = document.createElement('a');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.click();
    }

    // Focus tab management
    function openFocusTab(slotIndex) {
      const worker = state.layout?.slots?.[slotIndex];
      if (!worker) return;
      const existing = focusTabs.find(t => t.slotIndex === slotIndex);
      if (!existing) {
        focusTabs.push({ slotIndex, workspaceId: activeWorkspaceId.value, label: worker.name });
      }
      activeTab.value = 'focus-' + slotIndex;
      requestOutputCatchup(slotIndex, {
        workspaceId: activeWorkspaceId.value,
        workerType: worker.type,
        force: true,
      });
    }
    function closeFocusTab(slotIndex) {
      const idx = focusTabs.findIndex(t => t.slotIndex === slotIndex);
      if (idx >= 0) focusTabs.splice(idx, 1);
      if (activeTab.value === 'focus-' + slotIndex) {
        activeTab.value = 'workers';
        focusWorkerGridSoon();
      }
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
      const activeWorkerCount = (state.layout?.slots || []).filter(s => ['working', 'retrying'].includes(s?.state)).length;
      const workersLabel = activeWorkerCount > 0 ? `Workers (${activeWorkerCount})` : 'Workers';
      const tabs = [
        { id: 'tasks', label: 'Tickets', icon: 'tag' },
        { id: 'workers', label: workersLabel, icon: 'bot' },
        { id: 'files', label: 'Files', icon: 'folder' },
        { id: 'commits', label: 'Commits', icon: 'git-commit' },
      ];
      const wsId = activeWorkspaceId.value;
      const wsChatTabs = chatTabs.filter(ct => ct.workspaceId === wsId);
      for (const ct of wsChatTabs) {
        tabs.push({ id: ct.id, label: ct.label, isChat: true, canClose: wsChatTabs.length > 1, icon: 'message-square' });
      }
      for (const ft of focusTabs) {
        if (ft.workspaceId && ft.workspaceId !== wsId) continue;
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
      focusWorkerGridSoon();
    }
    function _hasPlaintextCommandWorkers() {
      const slots = state.layout?.slots || [];
      return slots.some(s => s && (s.type === 'shell' || s.type === 'service'));
    }
    function saveTeam(name) {
      if (_hasPlaintextCommandWorkers()) {
        const ok = confirm(
          'This team includes command-based workers. Their commands and env values will be saved in plaintext.\n\nContinue saving?'
        );
        if (!ok) return;
      }
      socket.emit('team:save', _wsData({ name }));
    }
    function loadTeam(name) {
      socket.emit('team:load', _wsData({ name }));
    }
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

    async function exportWorkers() {
      if (!activeWorkspaceId.value) return;
      try {
        const url = `/api/export/workers?workspaceId=${encodeURIComponent(activeWorkspaceId.value)}`;
        await _downloadZip(url, 'bullpen-workers.zip');
        addToast('Workers export ready');
      } catch (e) {
        addToast('Workers export failed: ' + e.message, 'error');
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

    async function importWorkers(file) {
      if (!activeWorkspaceId.value) return;
      try {
        const url = `/api/import/workers?workspaceId=${encodeURIComponent(activeWorkspaceId.value)}`;
        await _importZip(url, file, 'Workers import complete');
      } catch (e) {
        addToast('Workers import failed: ' + e.message, 'error');
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
    function setTheme(themeId, options = {}) {
      const next = _normalizeTheme(themeId);
      _applyTheme(next);
      if (activeWorkspaceId.value) {
        const ws = _getWs(activeWorkspaceId.value);
        ws.config = { ...(ws.config || {}), theme: next };
        if (_isActive(activeWorkspaceId.value)) state.config = ws.config;
        updateConfig({ theme: next });
      }
      if (options?.focusWorkerGrid) focusWorkerGridSoon();
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
    function setProviderColor(agent, color) {
      if (!activeWorkspaceId.value) return;
      const defaults = window.DEFAULT_AGENT_COLORS || {};
      if (!(agent in defaults)) return;
      if (typeof color !== 'string' || !HEX_COLOR_RE.test(color)) return;
      const ws = _getWs(activeWorkspaceId.value);
      const next = { ..._normalizeProviderColors(ws.config?.provider_colors), [agent]: color.toLowerCase() };
      ws.config = { ...(ws.config || {}), provider_colors: next };
      if (_isActive(activeWorkspaceId.value)) {
        state.config = ws.config;
        _applyWorkspaceProviderColors(activeWorkspaceId.value);
      }
      updateConfig({ provider_colors: next });
    }
    function resetProviderColors() {
      if (!activeWorkspaceId.value) return;
      const defaults = { ...(window.DEFAULT_AGENT_COLORS || {}) };
      const ws = _getWs(activeWorkspaceId.value);
      ws.config = { ...(ws.config || {}), provider_colors: defaults };
      if (_isActive(activeWorkspaceId.value)) {
        state.config = ws.config;
        _applyWorkspaceProviderColors(activeWorkspaceId.value);
      }
      updateConfig({ provider_colors: null });
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

    function _activateChatTabFromCommand() {
      const wsId = activeWorkspaceId.value;
      if (!wsId) {
        addToast('No active workspace to open chat', 'error');
        return;
      }
      const preferred = chatTabs.find(t => t.id === lastLiveAgentTabByWorkspace[wsId] && t.workspaceId === wsId);
      const existing = preferred || chatTabs.find(t => t.workspaceId === wsId);
      if (existing) {
        setActiveTab(existing.id);
        return;
      }
      addLiveAgentTab({ activate: true });
    }

    function _activateStandardTabFromCommand(name) {
      const key = String(name || '').trim().toLowerCase();
      if (key === 'tasks' || key === 'tickets') {
        setActiveTab('tasks');
        return true;
      }
      if (key === 'workers' || key === 'bullpen') {
        setActiveTab('workers');
        return true;
      }
      if (key === 'files') {
        setActiveTab('files');
        return true;
      }
      if (key === 'commits') {
        setActiveTab('commits');
        return true;
      }
      if (key === 'chat' || key === 'live') {
        _activateChatTabFromCommand();
        return true;
      }
      return false;
    }

    function setTicketsViewMode(mode) {
      const normalized = String(mode || '').trim().toLowerCase();
      if (normalized !== 'kanban' && normalized !== 'list') return;
      ticketsViewMode.value = normalized;
      setActiveTab('tasks');
    }

    function copyText(label, value) {
      const text = String(value || '').trim();
      if (!text) {
        addToast(`${label} is unavailable`, 'error');
        return;
      }
      if (!navigator.clipboard?.writeText) {
        addToast('Clipboard is unavailable in this browser', 'error');
        return;
      }
      navigator.clipboard.writeText(text)
        .then(() => addToast(`${label} copied`))
        .catch(e => addToast(`Copy failed: ${e.message}`, 'error'));
    }

    function getPaletteContext() {
      return {
        activeWorkspaceId: activeWorkspaceId.value,
        activeTab: activeTab.value,
        projectPath: state.workspace,
        themes: THEME_CATALOG,
        ambientPresets: AMBIENT_PRESETS,
        actions: {
          quickCreateTask,
          openCreateModal() { showCreateModal.value = true; },
          archiveDone,
          setTicketListScope,
          setActiveTab,
          setTicketsViewMode,
          openStandardTab: _activateStandardTabFromCommand,
          openChatTab: _activateChatTabFromCommand,
          addLiveAgentTab,
          toggleLeftPane,
          openColumnManager() { showColumnManager.value = true; },
          exportWorkspace,
          exportWorkers,
          exportAll,
          setTheme,
          setAmbientPreset,
          setAmbientVolume,
          addToast,
          copyText,
        },
      };
    }

    const paletteCommands = computed(() => {
      if (!window.BullpenCommands) return [];
      return window.BullpenCommands.buildCommands(getPaletteContext());
    });

    function runPaletteCommand(commandId, args = '') {
      const command = paletteCommands.value.find(item => item.id === commandId);
      if (!command) {
        addToast('Unknown command', 'error');
        return;
      }
      if (command.disabledReason) {
        addToast(command.disabledReason, 'error');
        return;
      }
      try {
        command.run(getPaletteContext(), args);
      } catch (e) {
        addToast(`Command failed: ${e.message}`, 'error');
      }
    }

    function runPaletteInput(input) {
      if (!window.BullpenCommands) return;
      const match = window.BullpenCommands.findCommand(paletteCommands.value, input);
      if (!match) {
        const parsed = window.BullpenCommands.parseCommandInput(input);
        addToast(`Unknown command ">${parsed.command}". Try >help`, 'error');
        return;
      }
      runPaletteCommand(match.command.id, match.args);
    }

    const themeOptions = computed(() => THEME_CATALOG.map(t => ({ id: t.id, label: t.label })));
    const currentTheme = computed(() => _normalizeTheme(state.config?.theme || 'dark'));
    const ambientPresets = computed(() => AMBIENT_PRESETS);
    const currentAmbientPreset = computed(() => _normalizeAmbientPreset(state.config?.ambient_preset) || '');
    const currentAmbientVolume = computed(() => _normalizeAmbientVolume(state.config?.ambient_volume));
    const currentProviderColors = computed(() => _normalizeProviderColors(state.config?.provider_colors));
    const defaultProviderColors = computed(() => ({ ...(window.DEFAULT_AGENT_COLORS || {}) }));
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
      return id;
    }

    function dismissToast(id) {
      const idx = toasts.findIndex(t => t.id === id);
      if (idx >= 0) toasts.splice(idx, 1);
    }

    function openCommitDiffFromTicket(hash) {
      const normalized = String(hash || '').trim();
      if (!/^[0-9a-f]{7,40}$/i.test(normalized)) {
        addToast('Invalid commit hash in ticket output', 'error');
        return;
      }
      activeTab.value = 'commits';
      requestedCommitDiffHash.value = '';
      setTimeout(() => {
        requestedCommitDiffHash.value = normalized;
      }, 0);
    }

    const multipleWorkspaces = computed(() => projects.length >= 2);

    return {
      state, workspaces, activeWorkspaceId, switchWorkspace, projects, projectsLoaded,
      addProject, newProject, cloneProject, removeProject,
      connected, activeTab, setActiveTab, requestedCommitDiffHash, leftPaneVisible, toasts, quickCreateClearToken,
      showCreateModal, showColumnManager, selectedTask, selectedTaskReadOnly, configureSlot, configureWorkerData,
      toggleLeftPane, setTheme, setAmbientPreset, setAmbientVolume, setProviderColor, resetProviderColors, themeOptions, currentTheme, ambientPresets, currentAmbientPreset, currentAmbientVolume, currentProviderColors, defaultProviderColors, createTask, quickCreateTask, updateTask, deleteTask, archiveTask, archiveDone, clearTaskOutput,
      paletteCommands, runPaletteCommand, runPaletteInput,
      moveTask, selectTask, addWorker, removeWorker, moveWorker, moveWorkerGroup, pasteWorkerConfig, pasteWorkerGroup,
      saveWorkerConfig, assignTask, startWorkerSlot,
      stopWorkerSlot, restartServiceSlot, openServiceSite, updateConfig, saveColumns, saveTeam, loadTeam, saveProfile, addToast, dismissToast,
      duplicateWorker, multipleWorkspaces,
      transferSlot, transferMode, openTransfer, transferWorker,
      closeCreateModal, closeColumnManager, closeWorkerConfig, closeTransferModal,
      outputBuffers, outputLinesForSlot, requestOutputCatchup, focusTabs, openFocusTab, closeFocusTab, focusTask, allTabs,
      ticketsViewMode, ticketListScope, setTicketListScope, visibleTicketTasks, chatTabs, addLiveAgentTab, closeLiveAgentTab,
      tabIcon, activeProjectName, exportWorkspace, exportWorkers, exportAll, importWorkspace, importWorkers, importAll, openCommitDiffFromTicket,
      bullpenTabRef,
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
        :project-path="state.workspace"
        :connected="connected"
        :themes="themeOptions"
        :active-theme="currentTheme"
        :ambient-presets="ambientPresets"
        :ambient-preset="currentAmbientPreset"
        :ambient-volume="currentAmbientVolume"
        :provider-colors="currentProviderColors"
        :default-provider-colors="defaultProviderColors"
        :quick-create-clear-token="quickCreateClearToken"
        :palette-commands="paletteCommands"
        @toggle-left-pane="toggleLeftPane"
        @export-workspace="exportWorkspace"
        @export-workers="exportWorkers"
        @export-all="exportAll"
        @import-workspace="importWorkspace"
        @import-workers="importWorkers"
        @import-all="importAll"
        @set-theme="setTheme"
        @set-ambient-preset="setAmbientPreset"
        @set-ambient-volume="setAmbientVolume"
        @set-provider-color="(agent, color) => setProviderColor(agent, color)"
        @reset-provider-colors="resetProviderColors"
        @quick-create-task="quickCreateTask"
        @run-palette-command="runPaletteCommand"
        @run-palette-input="runPaletteInput"
      />
      <div class="app-body">
        <LeftPane
          :tasks="state.tasks"
          :layout="state.layout"
          :config="state.config"
          :visible="leftPaneVisible"
          :projects="projects"
          :projects-loaded="projectsLoaded"
          :active-workspace-id="activeWorkspaceId"
          :workspaces="workspaces"
          @new-task="showCreateModal = true"
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
                @click="setActiveTab(tab.id)"
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
              <div id="worker-tab-toolbar-slot"></div>
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
              @update-task="updateTask"
              @archive-done="archiveDone"
              @new-task="showCreateModal = true"
              @update-list-scope="setTicketListScope"
            />
            <BullpenTab
              v-if="activeTab === 'workers'"
              ref="bullpenTabRef"
              :layout="state.layout"
              :config="state.config"
              :profiles="state.profiles"
              :tasks="state.tasks"
              :workspace="state.workspace"
              :workspace-id="activeWorkspaceId"
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
              :open-diff-hash="requestedCommitDiffHash"
              @handled-open-diff-hash="requestedCommitDiffHash = ''"
              :key="'commits-' + (activeWorkspaceId || 'none')"
            />
            <LiveAgentChatTab
              v-for="ct in chatTabs"
              v-show="activeTab === ct.id"
              :key="ct.id"
              :session-id="ct.sessionId"
              :workspace-id="ct.workspaceId"
            />
            <WorkerFocusView
              v-for="ft in focusTabs"
              v-show="activeTab === 'focus-' + ft.slotIndex"
              :key="'focus-' + ft.slotIndex"
              :worker="state.layout?.slots?.[ft.slotIndex]"
              :slot-index="ft.slotIndex"
              :task="focusTask(ft.slotIndex)"
              :output-lines="outputLinesForSlot(ft.slotIndex, ft.workspaceId)"
              @stop="stopWorkerSlot(ft.slotIndex)"
              @close="closeFocusTab(ft.slotIndex)"
            />
          </div>
        </div>
        <TaskDetailPanel
          :task="selectedTask"
          :columns="state.config.columns"
          :read-only="selectedTaskReadOnly"
          @close="selectTask(null)"
          @update="updateTask"
          @delete="deleteTask"
          @archive="archiveTask"
          @clear-output="clearTaskOutput"
          @toast="addToast"
          @open-commit-diff="openCommitDiffFromTicket"
        />
      </div>
      <TaskCreateModal
        :visible="showCreateModal"
        @close="closeCreateModal"
        @create="createTask"
      />
      <WorkerConfigModal
        :worker="configureWorkerData"
        :slot-index="configureSlot"
        :columns="state.config.columns"
        :workers="state.layout.slots"
        :grid-rows="state.config.grid?.rows || 4"
        :grid-cols="state.config.grid?.cols || 6"
        @close="closeWorkerConfig"
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
        @close="closeTransferModal"
        @transfer="transferWorker"
      />
      <ColumnManagerModal
        :visible="showColumnManager"
        :columns="state.config.columns"
        :tasks="state.tasks"
        @close="closeColumnManager"
        @save="saveColumns"
      />
      <ToastContainer :toasts="toasts" @dismiss="dismissToast" />
    </div>
  `
});

app.mount('#app');
