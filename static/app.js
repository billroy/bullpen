const { createApp, reactive, ref, computed } = Vue;

const app = createApp({
  components: {
    TopToolbar,
    LeftPane,
    KanbanTab,
    BullpenTab,
    FilesTab,
    StatsTab,
    CommitsTab,
    LiveAgentChatTab,
    TerminalTab,
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
      config: { name: 'Bullpen', grid: { layout: 'medium', columnWidth: 220, viewportOrigin: { col: 0, row: 0 } }, columns: [], ambient_preset: null, ambient_volume: 40, worker_automation_paused: false },
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
    const projectSettings = reactive({ projectsRoot: '' });
    const globalSettings = reactive({ version: 1, last_ai_selection: null });

    function _defaultWsData() {
      return {
        workspace: '',
        config: { name: 'Bullpen', grid: { layout: 'medium', columnWidth: 220, viewportOrigin: { col: 0, row: 0 } }, columns: [], ambient_preset: null, ambient_volume: 40, worker_automation_paused: false },
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
      const rowHeights = {};
      if (grid.rowHeights && typeof grid.rowHeights === 'object' && !Array.isArray(grid.rowHeights)) {
        for (const [key, value] of Object.entries(grid.rowHeights)) {
          const row = Number(key);
          const rawHeight = Number(value);
          if (!Number.isInteger(row) || row < 0 || !Number.isFinite(rawHeight)) continue;
          const height = Math.max(32, Math.min(480, Math.round(rawHeight)));
          if (rowHeight === undefined || height !== rowHeight) rowHeights[String(row)] = height;
        }
      }
      safe.grid = {
        columnWidth: Math.max(140, Math.min(480, Math.round(columnWidth / 20) * 20)),
        rowHeight,
        rowHeights,
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
      safe.worker_automation_paused = safe.worker_automation_paused === true;
      return safe;
    }

    function applyGlobalSettings(settings) {
      if (!settings || typeof settings !== 'object') return;
      globalSettings.version = Number(settings.version || 1);
      globalSettings.last_ai_selection = normalizedLastAiSelection(settings.last_ai_selection);
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
      const automationPaused = ws.config?.worker_automation_paused === true;
      window.ambientAudio.setVolume(volume / 100);
      if (automationPaused) {
        if (typeof window.ambientAudio.muteAmbient === 'function') {
          window.ambientAudio.muteAmbient();
        } else {
          window.ambientAudio.stopAmbient();
        }
        return;
      }
      if (typeof window.ambientAudio.unmuteAmbient === 'function') {
        window.ambientAudio.unmuteAmbient();
      }
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

    const ACTIVE_PROJECT_STORAGE_KEY = 'bullpen.activeWorkspaceId';
    const ACTIVE_TAB_STORAGE_KEY = 'bullpen.activeTab';
    const RESTORABLE_TAB_IDS = ['tasks', 'workers', 'files', 'commits', 'stats', 'chat'];

    function _rememberActiveWorkspace(wsId) {
      try {
        if (wsId) localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, wsId);
      } catch (e) { /* ignore */ }
    }

    function _loadRememberedWorkspace() {
      try {
        return localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY) || '';
      } catch (e) {
        return '';
      }
    }
    let pendingActiveWorkspaceRestore = _loadRememberedWorkspace();

    function _storageValueForActiveTab(tabId) {
      const id = String(tabId || '').trim();
      if (RESTORABLE_TAB_IDS.includes(id) && id !== 'chat') return id;
      if (chatTabs.find(t => t.id === id)) return 'chat';
      return '';
    }

    function _rememberActiveTab(tabId) {
      const stored = _storageValueForActiveTab(tabId);
      if (!stored) return;
      try {
        localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, stored);
      } catch (e) { /* ignore */ }
    }

    function _loadRememberedTab() {
      try {
        const tabId = localStorage.getItem(ACTIVE_TAB_STORAGE_KEY) || '';
        return RESTORABLE_TAB_IDS.includes(tabId) ? tabId : 'tasks';
      } catch (e) {
        return 'tasks';
      }
    }

    function _availableProjectIds() {
      return projects.filter(p => p.available !== false).map(p => p.id);
    }

    function _restoreWorkspaceAfterProjectsUpdate() {
      const availableIds = _availableProjectIds();
      if (!availableIds.length) return;
      const remembered = pendingActiveWorkspaceRestore;
      pendingActiveWorkspaceRestore = '';
      if (remembered && availableIds.includes(remembered)) {
        switchWorkspace(remembered);
        return;
      }
      if (activeWorkspaceId.value && availableIds.includes(activeWorkspaceId.value)) return;
      switchWorkspace(availableIds[0]);
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
      const currentWsId = activeWorkspaceId.value;
      const currentChatTab = chatTabs.find(t => t.id === activeTab.value && t.workspaceId === currentWsId);
      if (currentChatTab?.workspaceId) {
        lastLiveAgentTabByWorkspace[currentChatTab.workspaceId] = currentChatTab.id;
      }
      const wasLiveAgent = !!currentChatTab;
      activeWorkspaceId.value = wsId;
      _rememberActiveWorkspace(wsId);
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
      if (activeTab.value === 'stats') {
        socket.emit('task:list', _wsData({ scope: 'archived' }));
      }
      if (pendingActiveTabRestore === 'chat') {
        pendingActiveTabRestore = '';
        if (ensuredChatTab) {
          setActiveTab(ensuredChatTab.id);
          return;
        }
      } else if (pendingActiveTabRestore) {
        pendingActiveTabRestore = '';
      }
      if (wasLiveAgent) {
        const preferred = chatTabs.find(t => t.id === lastLiveAgentTabByWorkspace[wsId] && t.workspaceId === wsId);
        const fallback = preferred || ensuredChatTab || chatTabs.find(t => t.workspaceId === wsId);
        if (fallback) {
          setActiveTab(fallback.id);
        } else {
          setActiveTab('tasks');
        }
        return;
      }
      // If active tab belongs to a different workspace, fall back to tasks
      const ct = chatTabs.find(t => t.id === activeTab.value);
      if (ct && ct.workspaceId && ct.workspaceId !== wsId) { setActiveTab('tasks'); return; }
      const tt = terminalTabs.find(t => t.id === activeTab.value);
      if (tt && tt.workspaceId && tt.workspaceId !== wsId) { setActiveTab('tasks'); return; }
      const ft = focusTabs.find(t => 'focus-' + t.slotIndex === activeTab.value);
      if (ft && ft.workspaceId && ft.workspaceId !== wsId) setActiveTab('tasks');
    }

    const connected = ref(false);
    let pendingActiveTabRestore = _loadRememberedTab();
    const activeTab = ref(pendingActiveTabRestore === 'chat' ? 'tasks' : pendingActiveTabRestore);
    const requestedCommitDiffHash = ref('');
    const ticketsViewMode = ref('kanban');
    const ticketListScope = ref('live');
    const leftPaneVisible = ref(true);
    const workerMinimapCollapsed = ref(true);
    const toasts = reactive([]);
    const showCreateModal = ref(false);
    const showColumnManager = ref(false);
    const selectedTaskId = ref(null);
    const selectedTaskMode = ref('edit'); // 'edit' | 'read'
    const configureSlot = ref(null);
    const transferSlot = ref(null);
    const transferSlots = ref([]);
    const transferMode = ref('copy');
    const quickCreateClearToken = ref(0);
    const pendingQuickCreates = reactive([]);

    // Worker Focus Mode state
    const outputBuffers = reactive({});  // keyed by workspaceId + slot index
    const outputBufferMeta = reactive({});
    const focusTabs = reactive([]);      // [{slotIndex, workspaceId, label}]
    const chatTabs = reactive([]);
    const terminalTabs = reactive([]);
    const lastLiveAgentTabByWorkspace = reactive({});
    const terminalRefs = {};
    const terminalPendingOutput = {};
    let taskDragActive = false;
    const deferredTaskUpdates = new Map();
    let toastId = 0;

    function _taskUpdateKey(wsId, taskId) {
      return `${wsId || ''}:${taskId || ''}`;
    }

    function _sameTaskExceptLiveMetrics(current, next) {
      if (!current || !next) return false;
      const keys = new Set([...Object.keys(current), ...Object.keys(next)]);
      keys.delete('tokens');
      keys.delete('task_time_ms');
      keys.delete('reported_task_time_ms');
      keys.delete('active_task_started_at');
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
      window.BULLPEN_TASK_DRAG_ACTIVE = true;
    });
    window.addEventListener('bullpen:task-drag:end', () => {
      taskDragActive = false;
      window.BULLPEN_TASK_DRAG_ACTIVE = false;
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
      const wsId = activeWorkspaceId.value;
      const tab = chatTabs.find(t => t.id === tabId && t.workspaceId === wsId)
        || chatTabs.find(t => t.id === tabId);
      if (tab?.workspaceId) lastLiveAgentTabByWorkspace[tab.workspaceId] = tab.id;
    }

    function setActiveTab(tabId) {
      activeTab.value = tabId;
      _rememberLiveAgentTab(tabId);
      _rememberActiveTab(tabId);
      if (tabId === 'stats' && activeWorkspaceId.value) {
        socket.emit('task:list', _wsData({ scope: 'archived' }));
      }
      const term = _terminalTab(tabId);
      if (term) {
        Vue.nextTick(() => {
          terminalRefs[term.id]?.fit?.();
          terminalRefs[term.id]?.focus?.();
        });
      }
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
        else setActiveTab('tasks');
      }
    }

    function _terminalTabId(terminalId) {
      return 'terminal-' + terminalId;
    }

    function _terminalSize() {
      return { cols: 120, rows: 32 };
    }

    function _terminalTab(tabId) {
      return terminalTabs.find(t => t.id === tabId || t.terminalId === tabId);
    }

    function setTerminalRef(tabId, el) {
      if (el) terminalRefs[tabId] = el;
      else delete terminalRefs[tabId];
    }

    function flushTerminalOutput(tabId) {
      const ref = terminalRefs[tabId];
      const pending = terminalPendingOutput[tabId];
      if (!ref || !pending?.length) return;
      for (const chunk of pending) ref.write(chunk);
      delete terminalPendingOutput[tabId];
    }

    function addTerminalTab({ activate = true } = {}) {
      const wsId = activeWorkspaceId.value;
      if (!wsId) return null;
      const workspaceCount = terminalTabs.filter(t => t.workspaceId === wsId && t.status !== 'closed').length;
      const sessionCount = terminalTabs.filter(t => t.status !== 'closed').length;
      if (workspaceCount >= 8) {
        addToast('Terminal limit reached for this workspace', 'error');
        return null;
      }
      if (sessionCount >= 24) {
        addToast('Terminal limit reached for this browser session', 'error');
        return null;
      }
      const terminalId = crypto.randomUUID();
      const perWsCount = workspaceCount + 1;
      const tab = {
        id: _terminalTabId(terminalId),
        terminalId,
        workspaceId: wsId,
        label: perWsCount === 1 ? 'Terminal' : `Terminal ${perWsCount}`,
        status: 'starting',
        cwd: '',
      };
      terminalTabs.push(tab);
      if (activate) setActiveTab(tab.id);
      socket.emit('terminal:create', _wsData({ terminalId, ..._terminalSize() }));
      return tab;
    }

    function closeTerminalTab(tabId) {
      const tab = _terminalTab(tabId);
      if (!tab) return;
      if (['running', 'starting'].includes(tab.status)) {
        const ok = confirm('Close this terminal and stop its shell?');
        if (!ok) return;
      }
      tab.status = 'closing';
      socket.emit('terminal:close', { workspaceId: tab.workspaceId, terminalId: tab.terminalId });
      setTimeout(() => {
        if (_terminalTab(tab.id)?.status === 'closing') removeTerminalTab(tab.id);
      }, connected.value ? 1500 : 0);
    }

    function removeTerminalTab(tabId) {
      const idx = terminalTabs.findIndex(t => t.id === tabId || t.terminalId === tabId);
      if (idx < 0) return;
      const tab = terminalTabs[idx];
      terminalTabs.splice(idx, 1);
      delete terminalRefs[tab.id];
      delete terminalPendingOutput[tab.id];
      if (activeTab.value === tab.id) {
        const fallback = terminalTabs.find(t => t.workspaceId === tab.workspaceId) || chatTabs.find(t => t.workspaceId === tab.workspaceId);
        if (fallback) setActiveTab(fallback.id);
        else setActiveTab('tasks');
      }
    }

    function restartTerminal(tabId) {
      const tab = _terminalTab(tabId);
      if (!tab) return;
      tab.status = 'starting';
      terminalRefs[tab.id]?.clear?.();
      socket.emit('terminal:restart', {
        workspaceId: tab.workspaceId,
        terminalId: tab.terminalId,
        ..._terminalSize(),
      });
    }

    function sendTerminalInput({ terminalId, data }) {
      const tab = _terminalTab(terminalId);
      if (!tab) return;
      socket.emit('terminal:input', { workspaceId: tab.workspaceId, terminalId, data });
    }

    function resizeTerminal({ terminalId, cols, rows }) {
      const tab = _terminalTab(terminalId);
      if (!tab || !cols || !rows) return;
      socket.emit('terminal:resize', { workspaceId: tab.workspaceId, terminalId, cols, rows });
    }

    function onTerminalReady(tabId) {
      flushTerminalOutput(tabId);
      terminalRefs[tabId]?.fit?.();
      if (activeTab.value === tabId) terminalRefs[tabId]?.focus?.();
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
      transports: ['polling', 'websocket'],
    });
    window._bullpenSocket = socket;

    if (window.EventSounds) window.EventSounds.init(socket);
    if (window.NotificationWorkers) window.NotificationWorkers.init(socket);

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
      for (const tab of terminalTabs) {
        if (['running', 'starting'].includes(tab.status)) tab.status = 'error';
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
      applyGlobalSettings(data.globalSettings);

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
      if (taskDragActive && current && _sameTaskExceptLiveMetrics(current, task)) {
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
      if (_isActive(wsId) && activeTab.value === 'stats') {
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
    socket.on('global:settings', (settings) => {
      applyGlobalSettings(settings);
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
    socket.on('toast', (data) => {
      addToast((data && data.message) || 'Notification', (data && data.level) || 'info');
    });
    socket.on('error', (data) => { addToast((data && data.message) || 'An error occurred', 'error'); });
    socket.on('project:clone:started', (data) => {
      const target = data?.path ? ` into ${data.path}` : '';
      addToast(`Cloning ${data?.url || 'repository'}${target}`);
    });
    socket.on('project:clone:succeeded', (data) => {
      const target = data?.path ? `: ${data.path}` : '';
      addToast(`Clone complete${target}`);
    });
    socket.on('projects:updated', (list) => {
      projects.splice(0, projects.length, ...list);
      projectsLoaded.value = true;
      _restoreWorkspaceAfterProjectsUpdate();
    });
    socket.on('project:settings', (settings) => {
      projectSettings.projectsRoot = typeof settings?.projectsRoot === 'string' ? settings.projectsRoot : '';
    });
    socket.on('project:removed', (data) => {
      const removedId = data.workspaceId;
      delete workspaces[removedId];
      for (let i = chatTabs.length - 1; i >= 0; i -= 1) {
        if (chatTabs[i].workspaceId === removedId) chatTabs.splice(i, 1);
      }
      for (let i = terminalTabs.length - 1; i >= 0; i -= 1) {
        if (terminalTabs[i].workspaceId === removedId) terminalTabs.splice(i, 1);
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
        else setActiveTab('tasks');
      }
    });

    socket.on('terminal:created', (data) => {
      const wsId = data?.workspaceId || activeWorkspaceId.value;
      const terminalId = data?.terminalId;
      if (!terminalId || !wsId) return;
      const id = _terminalTabId(terminalId);
      let tab = terminalTabs.find(t => t.id === id);
      if (!tab) {
        tab = { id, terminalId, workspaceId: wsId, label: data.label || 'Terminal', status: 'running', cwd: data.cwd || '' };
        terminalTabs.push(tab);
      }
      tab.workspaceId = wsId;
      tab.label = data.label || tab.label || 'Terminal';
      tab.status = data.status || 'running';
      tab.cwd = data.cwd || tab.cwd || '';
      Vue.nextTick(() => onTerminalReady(tab.id));
    });

    socket.on('terminal:output', (data) => {
      const tab = _terminalTab(data?.terminalId);
      if (!tab) return;
      const ref = terminalRefs[tab.id];
      if (ref) {
        ref.write(data?.data || '');
        return;
      }
      const pending = terminalPendingOutput[tab.id] || [];
      pending.push(data?.data || '');
      let total = pending.reduce((sum, chunk) => sum + chunk.length, 0);
      while (total > 256000 && pending.length > 1) {
        total -= pending.shift().length;
      }
      terminalPendingOutput[tab.id] = pending;
    });

    socket.on('terminal:exit', (data) => {
      const tab = _terminalTab(data?.terminalId);
      if (tab) tab.status = 'exited';
    });

    socket.on('terminal:closed', (data) => {
      const tab = _terminalTab(data?.terminalId);
      if (tab) removeTerminalTab(tab.id);
    });

    socket.on('terminal:error', (data) => {
      const tab = _terminalTab(data?.terminalId);
      if (tab) tab.status = 'error';
      addToast(data?.message || 'Terminal error', 'error');
    });

    socket.on('terminal:list', (data) => {
      const wsId = data?.workspaceId || activeWorkspaceId.value;
      const incoming = Array.isArray(data?.terminals) ? data.terminals : [];
      for (const item of incoming) {
        if (!item?.terminalId) continue;
        const id = _terminalTabId(item.terminalId);
        let tab = terminalTabs.find(t => t.id === id);
        if (!tab) {
          tab = { id, terminalId: item.terminalId, workspaceId: wsId, label: item.label || 'Terminal', status: item.status || 'running', cwd: item.cwd || '' };
          terminalTabs.push(tab);
        } else {
          tab.workspaceId = wsId;
          tab.label = item.label || tab.label;
          tab.status = item.status || tab.status;
          tab.cwd = item.cwd || tab.cwd;
        }
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
      if (!socket?.connected) {
        addToast('Disconnected from Bullpen server. Ticket was not created.', 'error');
        return;
      }
      pendingQuickCreates.push({ title, description });
      socket.emit('task:create', _wsData({ title, type: 'task', priority: 'normal', tags: [], description }));
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
    function archiveColumnTasks({ status }) {
      const affected = state.tasks.filter(t => t.status === status);
      if (!affected.length) return false;
      if (!socket?.connected) {
        addToast('Disconnected from Bullpen server. Tickets were not archived.', 'error');
        return false;
      }
      socket.emit('task:archive-column', _wsData({ status }));
      return true;
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
    function moveColumnTasks({ fromStatus, toStatus }) {
      if (!fromStatus || !toStatus || fromStatus === toStatus) return false;
      const affected = state.tasks.filter(t => t.status === fromStatus);
      if (!affected.length) return false;
      if (!socket?.connected) {
        addToast('Disconnected from Bullpen server. Ticket moves were not saved.', 'error');
        return false;
      }
      for (const task of affected) {
        socket.emit('task:update', _wsData({ id: task.id, status: toStatus }));
      }
      return true;
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

    function setTicketListShownCount(count) {
      ticketListShownCount.value = Number.isFinite(count) ? count : 0;
    }

    // Worker actions
    function addWorker({ slot, coord, profile, type, fields }) {
      socket.emit('worker:add', _wsData({ slot, coord, profile, type, fields }));
    }
    function workerDeleteMessage(workers) {
      if (!workers.length) return '';
      if (workers.length === 1) {
        const { slot, worker } = workers[0];
        const name = worker?.name || `Slot ${slot + 1}`;
        const queued = Number(worker?.task_queue?.length || 0);
        return queued > 0
          ? `Delete worker "${name}"?\n\nThis worker has ${queued} queued task(s).`
          : `Delete worker "${name}"?`;
      }
      const queued = workers.reduce((total, { worker }) => total + Number(worker?.task_queue?.length || 0), 0);
      return queued > 0
        ? `Delete ${workers.length} workers?\n\nThese workers have ${queued} queued task(s).`
        : `Delete ${workers.length} workers?`;
    }
    function removeWorker(slot) {
      const worker = state.layout?.slots?.[slot];
      const confirmMessage = workerDeleteMessage([{ slot, worker }]);
      if (!confirm(confirmMessage)) return;
      socket.emit('worker:remove', _wsData({ slot }));
    }
    function removeWorkers(slots) {
      const seen = new Set();
      const workers = [];
      for (const rawSlot of slots || []) {
        const slot = Number(rawSlot);
        if (!Number.isInteger(slot) || seen.has(slot)) continue;
        seen.add(slot);
        const worker = state.layout?.slots?.[slot];
        if (worker) workers.push({ slot, worker });
      }
      if (workers.length <= 1) {
        if (workers.length === 1) removeWorker(workers[0].slot);
        return;
      }
      if (!confirm(workerDeleteMessage(workers))) return;
      socket.emit('worker:remove_many', _wsData({ slots: workers.map(({ slot }) => slot) }));
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
    function duplicateWorkers(slots) { socket.emit('worker:duplicate_group', _wsData({ slots })); }
    function openTransfer({ slot, slots, mode }) {
      const resolvedSlots = Array.isArray(slots) && slots.length ? slots.map(Number).filter(Number.isInteger) : [];
      transferSlot.value = Number.isInteger(Number(slot)) ? Number(slot) : (resolvedSlots[0] ?? null);
      transferSlots.value = resolvedSlots.length ? resolvedSlots : (transferSlot.value !== null ? [transferSlot.value] : []);
      transferMode.value = mode;
    }
    function copyWorkerFromLeftPane(slot) {
      const copy = () => bullpenTabRef.value?.copyWorker?.(slot);
      if (bullpenTabRef.value?.copyWorker) {
        copy();
        return;
      }
      setActiveTab('workers');
      Vue.nextTick(copy);
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
      transferSlots.value = [];
      focusWorkerGridSoon();
    }
    function _requestWorkerTransfer(payload) {
      return new Promise((resolve, reject) => {
        const expectedWorkspaceId = payload.source_workspace_id || payload.workspaceId || activeWorkspaceId.value;
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('Worker transfer timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('worker:transferred', onTransferred);
          socket.off('worker:transfer:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload) return false;
          if (expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onTransferred = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'Transfer failed'));
        };
        socket.on('worker:transferred', onTransferred);
        socket.on('worker:transfer:error', onError);
        socket.emit('worker:transfer', _wsData(payload));
      });
    }
    let servicePreviewRequestSeq = 0;
    function requestServicePreview(payload) {
      return new Promise((resolve, reject) => {
        const requestId = `service-preview-${Date.now()}-${++servicePreviewRequestSeq}`;
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('Service preview timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('service:previewed', onPreviewed);
          socket.off('service:preview:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload || eventPayload.request_id !== requestId) return false;
          if (expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onPreviewed = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'Preview unavailable'));
        };
        socket.on('service:previewed', onPreviewed);
        socket.on('service:preview:error', onError);
        socket.emit('service:preview', _wsData({ ...payload, request_id: requestId }));
      });
    }
    let openCodeModelsRequestSeq = 0;
    function requestOpenCodeModels(payload = {}) {
      return new Promise((resolve, reject) => {
        const requestId = `opencode-models-${Date.now()}-${++openCodeModelsRequestSeq}`;
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('OpenCode model catalog timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('models:opencode:listed', onListed);
          socket.off('models:opencode:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload || eventPayload.request_id !== requestId) return false;
          if (expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onListed = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'OpenCode model catalog is unavailable'));
        };
        socket.on('models:opencode:listed', onListed);
        socket.on('models:opencode:error', onError);
        socket.emit('models:opencode', _wsData({ ...payload, request_id: requestId }));
      });
    }
    let commitsRequestSeq = 0;
    function requestCommits(payload = {}) {
      return new Promise((resolve, reject) => {
        const requestId = `commits-list-${Date.now()}-${++commitsRequestSeq}`;
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('Commit list timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('commits:listed', onListed);
          socket.off('commits:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload || eventPayload.request_id !== requestId) return false;
          if (expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onListed = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'Failed to load commits'));
        };
        socket.on('commits:listed', onListed);
        socket.on('commits:error', onError);
        socket.emit('commits:list', _wsData({ ...payload, request_id: requestId }));
      });
    }
    function requestCommitDiff(payload = {}) {
      return new Promise((resolve, reject) => {
        const requestId = `commits-diff-${Date.now()}-${++commitsRequestSeq}`;
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('Commit diff timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('commits:diffed', onDiffed);
          socket.off('commits:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload || eventPayload.request_id !== requestId) return false;
          if (expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onDiffed = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'Failed to load diff'));
        };
        socket.on('commits:diffed', onDiffed);
        socket.on('commits:error', onError);
        socket.emit('commits:diff', _wsData({ ...payload, request_id: requestId }));
      });
    }
    let filesRequestSeq = 0;
    function _requestFileEvent({ requestEvent, successEvent, payload = {}, timeoutMessage, errorMessage }) {
      return new Promise((resolve, reject) => {
        const requestId = `files-${Date.now()}-${++filesRequestSeq}`;
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error(timeoutMessage || 'File request timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off(successEvent, onSuccess);
          socket.off('files:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload || eventPayload.request_id !== requestId) return false;
          if (expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onSuccess = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || errorMessage || 'File request failed'));
        };
        socket.on(successEvent, onSuccess);
        socket.on('files:error', onError);
        socket.emit(requestEvent, _wsData({ ...payload, request_id: requestId }));
      });
    }
    function requestFileTree(payload = {}) {
      return _requestFileEvent({
        requestEvent: 'files:list',
        successEvent: 'files:listed',
        payload,
        timeoutMessage: 'File tree request timed out',
        errorMessage: 'Could not load files',
      });
    }
    function requestFileRead(payload = {}) {
      return _requestFileEvent({
        requestEvent: 'files:read',
        successEvent: 'files:read',
        payload,
        timeoutMessage: 'File read timed out',
        errorMessage: 'Failed to load file',
      });
    }
    function requestFileBinary(payload = {}) {
      return _requestFileEvent({
        requestEvent: 'files:binary',
        successEvent: 'files:binary',
        payload,
        timeoutMessage: 'File download timed out',
        errorMessage: 'Failed to load file',
      });
    }
    function requestFileExists(payload = {}) {
      return _requestFileEvent({
        requestEvent: 'files:exists',
        successEvent: 'files:exists:result',
        payload,
        timeoutMessage: 'File existence check timed out',
        errorMessage: 'Could not verify whether that file exists.',
      });
    }
    function requestFileWrite(payload = {}) {
      return _requestFileEvent({
        requestEvent: 'files:write',
        successEvent: 'files:written',
        payload,
        timeoutMessage: 'File save timed out',
        errorMessage: 'Save failed',
      });
    }
    async function transferWorker(payload) {
      try {
        const groupTransfer = Array.isArray(payload.source_slots) && payload.source_slots.length > 1;
        const data = await _requestWorkerTransfer(payload);
        const destName = projects.find(p => p.id === payload.dest_workspace_id)?.name || 'workspace';
        const subject = groupTransfer ? `${payload.source_slots.length} workers` : 'Worker';
        addToast(`${subject} ${payload.mode === 'move' ? 'moved' : 'copied'} to ${destName}`);
        if (data.warnings?.length) {
          for (const w of data.warnings) addToast(w, 'error');
        }
      } catch (e) {
        addToast('Transfer failed: ' + e.message, 'error');
      }
      closeTransferModal();
    }
    function saveWorkerConfig({ slot, fields }) { socket.emit('worker:configure', _wsData({ slot, fields })); }
    function saveWorkersConfig({ slots, fields }) { socket.emit('worker:configure_many', _wsData({ slots, fields })); }

    // Execution actions
    function assignTask(taskId, slot) { socket.emit('task:assign', _wsData({ task_id: taskId, slot })); }
    function _workerAt(slot) {
      return state.layout?.slots?.[slot] || null;
    }
    function startWorkerSlot(slot) {
      const worker = _workerAt(slot);
      const hasQueuedOrder = worker?.type === 'service' && Array.isArray(worker.task_queue) && worker.task_queue.length > 0;
      socket.emit(worker?.type === 'service' && !hasQueuedOrder ? 'service:start' : 'worker:start', _wsData({ slot }));
    }
    function stopWorkerSlot(slot) {
      const worker = _workerAt(slot);
      socket.emit(worker?.type === 'service' ? 'service:stop' : 'worker:stop', _wsData({ slot }));
    }
    function stopWorkerSlots(slots) { socket.emit('worker:stop_many', _wsData({ slots })); }
    function restartServiceSlot(slot) {
      socket.emit('service:restart', _wsData({ slot }));
    }
    function pauseAutomation() {
      socket.emit('workers:pause_automation', _wsData({}));
    }
    function resumeAutomation() {
      socket.emit('workers:resume_automation', _wsData({}));
    }
    function stopTheLine() {
      socket.emit('workers:stop_line', _wsData({}));
    }
    function pauseAllAutomation() {
      socket.emit('workers:pause_all_automation', {});
    }
    function resumeAllAutomation() {
      socket.emit('workers:resume_all_automation', {});
    }
    function stopAllLines() {
      socket.emit('workers:stop_all_lines', {});
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
      setActiveTab('focus-' + slotIndex);
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
        setActiveTab('workers');
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
      if (tab.isTerminal) return 'terminal';
      return ({
        tasks: 'tag',
        workers: 'bot',
        files: 'folder',
        stats: 'chart-no-axes-column',
        commits: 'git-commit',
      })[tab.id] || 'circle';
    }

    const allTabs = computed(() => {
      if (!activeWorkspaceId.value) return [];
      const activeWorkerCount = (state.layout?.slots || []).filter(s => ['working', 'retrying'].includes(s?.state)).length;
      const shownTicketCount = Number.isFinite(ticketListShownCount.value) ? ticketListShownCount.value : visibleTicketTasks.value.length;
      const ticketsLabel = ticketsViewMode.value === 'list' ? `Tickets (${shownTicketCount})` : 'Tickets';
      const workersLabel = activeWorkerCount > 0 ? `Workers (${activeWorkerCount})` : 'Workers';
      const tabs = [
        { id: 'tasks', label: ticketsLabel, icon: 'tag' },
        { id: 'workers', label: workersLabel, icon: 'bot' },
        { id: 'files', label: 'Files', icon: 'folder' },
        { id: 'commits', label: 'Commits', icon: 'git-commit' },
        { id: 'stats', label: 'Stats', icon: 'chart-no-axes-column' },
      ];
      const wsId = activeWorkspaceId.value;
      const wsChatTabs = chatTabs.filter(ct => ct.workspaceId === wsId);
      for (const ct of wsChatTabs) {
        tabs.push({ id: ct.id, label: ct.label, isChat: true, canClose: wsChatTabs.length > 1, icon: 'message-square' });
      }
      for (const tt of terminalTabs) {
        if (tt.workspaceId && tt.workspaceId !== wsId) continue;
        tabs.push({ id: tt.id, label: tt.label, isTerminal: true, canClose: true, icon: 'terminal' });
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
    function cloneProject(data) { socket.emit('project:clone', _wsData(data)); }
    function removeProject(wsId) { socket.emit('project:remove', { workspaceId: wsId }); }

    function toggleLeftPane() { leftPaneVisible.value = !leftPaneVisible.value; }
    function setWorkerMinimapCollapsed(collapsed) {
      workerMinimapCollapsed.value = collapsed === true;
    }

    function _nextRequestId(prefix) {
      const random = Math.random().toString(36).slice(2);
      return `${prefix}-${Date.now()}-${random}`;
    }

    function _downloadBlob(blob, fallbackName) {
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = fallbackName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    }

    function _bentoPayloadBytes(data) {
      if (data instanceof ArrayBuffer) return data;
      if (data instanceof Uint8Array) return data;
      if (Array.isArray(data)) return new Uint8Array(data);
      return data;
    }

    function _requestBentoExport(payload) {
      return new Promise((resolve, reject) => {
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const expectedKind = payload.kind;
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('Bento export timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('bento:exported', onExported);
          socket.off('bento:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload) return false;
          if (expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          if (expectedKind && eventPayload.kind && eventPayload.kind !== expectedKind) return false;
          return true;
        };
        const onExported = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'Bento export failed'));
        };
        socket.on('bento:exported', onExported);
        socket.on('bento:error', onError);
        socket.emit('bento:export', _wsData(payload));
      });
    }

    async function _downloadBentoExport(payload, fallbackName) {
      const exported = await _requestBentoExport(payload);
      const bytes = _bentoPayloadBytes(exported.data);
      const blob = new Blob([bytes], { type: exported.mimetype || 'application/vnd.bullpen.bento+zip' });
      _downloadBlob(blob, exported.filename || fallbackName);
      return exported;
    }

    function _requestArchiveExport(payload) {
      return new Promise((resolve, reject) => {
        const requestId = payload.request_id || _nextRequestId('archive-export');
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const expectedKind = payload.kind || 'workspace';
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('Archive export timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('archive:exported', onExported);
          socket.off('archive:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload) return false;
          if (eventPayload.request_id && eventPayload.request_id !== requestId) return false;
          if (expectedKind && eventPayload.kind && eventPayload.kind !== expectedKind) return false;
          if (expectedKind === 'workspace' && expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onExported = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'Archive export failed'));
        };
        socket.on('archive:exported', onExported);
        socket.on('archive:error', onError);
        socket.emit('archive:export', _wsData({ ...payload, request_id: requestId }));
      });
    }

    async function _downloadArchiveExport(payload, fallbackName) {
      const exported = await _requestArchiveExport(payload);
      const bytes = _bentoPayloadBytes(exported.data);
      const blob = new Blob([bytes], { type: exported.mimetype || 'application/zip' });
      _downloadBlob(blob, exported.filename || fallbackName);
      return exported;
    }

    function _requestBentoPreview(payload) {
      return new Promise((resolve, reject) => {
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('Bento preview timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('bento:previewed', onPreviewed);
          socket.off('bento:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload) return false;
          if (expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onPreviewed = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'Bento preview failed'));
        };
        socket.on('bento:previewed', onPreviewed);
        socket.on('bento:error', onError);
        socket.emit('bento:preview', _wsData(payload));
      });
    }

    function _requestBentoImport(payload) {
      return new Promise((resolve, reject) => {
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('Bento import timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('bento:imported', onImported);
          socket.off('bento:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload) return false;
          if (expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onImported = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'Bento import failed'));
        };
        socket.on('bento:imported', onImported);
        socket.on('bento:error', onError);
        socket.emit('bento:import', _wsData(payload));
      });
    }

    function _bentoImportCount(imported) {
      if (!imported || typeof imported !== 'object') return 0;
      return Object.values(imported).reduce((total, value) => {
        return total + (Number.isFinite(Number(value)) ? Number(value) : 0);
      }, 0);
    }

    const BENTO_RISKY_CAPABILITY_LABELS = {
      commands: 'command fields',
      env: 'environment variables',
      services: 'service worker settings',
      notifications: 'notification settings',
      git: 'git automation settings',
    };

    function _bentoImportApprovalsForPreview(preview) {
      const capabilities = preview?.bullpen?.capabilities;
      if (!capabilities || typeof capabilities !== 'object') return null;
      const approvals = {};
      for (const [capability, label] of Object.entries(BENTO_RISKY_CAPABILITY_LABELS)) {
        const count = Number(capabilities[capability] || 0);
        if (!Number.isFinite(count) || count <= 0) continue;
        approvals[capability] = window.confirm(
          `This package includes ${label} on ${count} worker${count === 1 ? '' : 's'}.\n\n` +
          'Preserve this capability for this import? Cancel imports it stripped.'
        );
      }
      return Object.keys(approvals).length ? approvals : null;
    }

    function _bentoImportPayloadForPreview(data, preview) {
      const payload = { file: data };
      const placement = preview?.bullpen?.placement;
      if (placement?.status === 'conflict') {
        throw new Error('Bento import has placement conflicts; placement review is required');
      }
      if (placement?.status === 'available' && placement?.state) {
        payload.placement = { strategy: 'preserve', state: placement.state };
      }
      const approvals = _bentoImportApprovalsForPreview(preview);
      if (approvals) {
        payload.approvals = approvals;
      }
      return payload;
    }

    async function _importBentoFile(file) {
      if (!file) return null;
      const data = await file.arrayBuffer();
      const preview = await _requestBentoPreview({ file: data });
      return _requestBentoImport(_bentoImportPayloadForPreview(data, preview));
    }

    function _requestArchiveImport(payload) {
      return new Promise((resolve, reject) => {
        const requestId = payload.request_id || _nextRequestId('archive-import');
        const expectedWorkspaceId = payload.workspaceId || activeWorkspaceId.value;
        const expectedKind = payload.kind || 'workspace';
        const timer = setTimeout(() => {
          cleanup();
          reject(new Error('Archive import timed out'));
        }, 30000);
        const cleanup = () => {
          clearTimeout(timer);
          socket.off('archive:imported', onImported);
          socket.off('archive:error', onError);
        };
        const matches = (eventPayload) => {
          if (!eventPayload) return false;
          if (eventPayload.request_id && eventPayload.request_id !== requestId) return false;
          if (expectedKind && eventPayload.kind && eventPayload.kind !== expectedKind) return false;
          if (expectedKind === 'workspace' && expectedWorkspaceId && eventPayload.workspaceId && eventPayload.workspaceId !== expectedWorkspaceId) return false;
          return true;
        };
        const onImported = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          resolve(eventPayload);
        };
        const onError = (eventPayload) => {
          if (!matches(eventPayload)) return;
          cleanup();
          reject(new Error(eventPayload.error || 'Archive import failed'));
        };
        socket.on('archive:imported', onImported);
        socket.on('archive:error', onError);
        socket.emit('archive:import', _wsData({ ...payload, request_id: requestId }));
      });
    }

    async function _importArchiveFile(file, kind) {
      if (!file) return null;
      const data = await file.arrayBuffer();
      return _requestArchiveImport({ kind, file: data });
    }

    async function exportWorkspace() {
      if (!activeWorkspaceId.value) return;
      try {
        await _downloadArchiveExport({ kind: 'workspace' }, 'bullpen-workspace.zip');
        addToast('Workspace export ready');
      } catch (e) {
        addToast('Workspace export failed: ' + e.message, 'error');
      }
    }

    async function exportWorkers() {
      if (!activeWorkspaceId.value) return;
      try {
        const slots = (state.layout?.slots || [])
          .map((worker, slot) => (worker ? slot : null))
          .filter(Number.isInteger);
        if (!slots.length) {
          addToast('No workers to export', 'error');
          return;
        }
        await _downloadBentoExport({ kind: 'worker-group', slots }, 'bullpen-workers.bento');
        addToast('Workers export ready');
      } catch (e) {
        addToast('Workers export failed: ' + e.message, 'error');
      }
    }

    async function exportWorker(slot) {
      if (!activeWorkspaceId.value || !Number.isInteger(slot)) return;
      try {
        await _downloadBentoExport({ kind: 'worker', slot }, 'bullpen-worker.bento');
        addToast('Worker export ready');
      } catch (e) {
        addToast('Worker export failed: ' + e.message, 'error');
      }
    }
    async function exportWorkerGroup(slots) {
      const validSlots = (slots || []).map(Number).filter(Number.isInteger);
      if (!activeWorkspaceId.value || !validSlots.length) return;
      try {
        await _downloadBentoExport({ kind: 'worker-group', slots: validSlots }, 'bullpen-worker-group.bento');
        addToast(validSlots.length === 1 ? 'Worker export ready' : 'Worker group export ready');
      } catch (e) {
        addToast('Worker export failed: ' + e.message, 'error');
      }
    }

    async function exportAll() {
      try {
        await _downloadArchiveExport({ kind: 'all' }, 'bullpen-all.zip');
        addToast('All-workspace export ready');
      } catch (e) {
        addToast('Export all failed: ' + e.message, 'error');
      }
    }

    async function importWorkspace(file) {
      if (!activeWorkspaceId.value) return;
      try {
        const result = await _importArchiveFile(file, 'workspace');
        addToast('Workspace import complete' + (result?.imported ? ` (${result.imported})` : ''));
      } catch (e) {
        addToast('Workspace import failed: ' + e.message, 'error');
      }
    }

    async function importWorkers(file) {
      if (!activeWorkspaceId.value) return;
      try {
        const result = await _importBentoFile(file);
        const count = _bentoImportCount(result?.imported);
        addToast('Package import complete' + (count ? ` (${count})` : ''));
      } catch (e) {
        addToast('Package import failed: ' + e.message, 'error');
      }
    }

    async function importAll(file) {
      try {
        const result = await _importArchiveFile(file, 'all');
        addToast('All-workspace import complete' + (result?.imported ? ` (${result.imported})` : ''));
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
          archiveColumnTasks,
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
    const ticketListShownCount = ref(null);
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
      setActiveTab('commits');
      requestedCommitDiffHash.value = '';
      setTimeout(() => {
        requestedCommitDiffHash.value = normalized;
      }, 0);
    }

    const multipleWorkspaces = computed(() => projects.length >= 2);
    const taskById = computed(() => {
      const map = {};
      for (const task of state.tasks || []) {
        if (task?.id) map[task.id] = task;
      }
      return map;
    });

    return {
      state, workspaces, activeWorkspaceId, switchWorkspace, projects, projectsLoaded, projectSettings, globalSettings,
      addProject, newProject, cloneProject, removeProject,
      connected, activeTab, setActiveTab, requestedCommitDiffHash, leftPaneVisible, workerMinimapCollapsed, setWorkerMinimapCollapsed, toasts, quickCreateClearToken,
      showCreateModal, showColumnManager, selectedTask, selectedTaskReadOnly, configureSlot, configureWorkerData,
      toggleLeftPane, setTheme, setAmbientPreset, setAmbientVolume, setProviderColor, resetProviderColors, themeOptions, currentTheme, ambientPresets, currentAmbientPreset, currentAmbientVolume, currentProviderColors, defaultProviderColors, createTask, quickCreateTask, updateTask, deleteTask, archiveTask, archiveColumnTasks, archiveDone, clearTaskOutput,
      paletteCommands, runPaletteCommand, runPaletteInput,
      moveTask, moveColumnTasks, selectTask, addWorker, removeWorker, removeWorkers, moveWorker, moveWorkerGroup, pasteWorkerConfig, pasteWorkerGroup,
      saveWorkerConfig, saveWorkersConfig, assignTask, startWorkerSlot,
      stopWorkerSlot, stopWorkerSlots, restartServiceSlot, requestServicePreview, requestOpenCodeModels, requestCommits, requestCommitDiff, requestFileTree, requestFileRead, requestFileBinary, requestFileExists, requestFileWrite, pauseAutomation, resumeAutomation, stopTheLine, pauseAllAutomation, resumeAllAutomation, stopAllLines, openServiceSite, updateConfig, saveColumns, saveTeam, loadTeam, saveProfile, addToast, dismissToast,
      duplicateWorker, duplicateWorkers, multipleWorkspaces, taskById,
      transferSlot, transferSlots, transferMode, openTransfer, transferWorker,
      copyWorkerFromLeftPane,
      closeCreateModal, closeColumnManager, closeWorkerConfig, closeTransferModal,
      outputBuffers, outputLinesForSlot, requestOutputCatchup, focusTabs, openFocusTab, closeFocusTab, focusTask, allTabs,
      ticketsViewMode, ticketListScope, setTicketListScope, visibleTicketTasks, chatTabs, addLiveAgentTab, closeLiveAgentTab,
      terminalTabs, addTerminalTab, closeTerminalTab, restartTerminal, sendTerminalInput, resizeTerminal, setTerminalRef, onTerminalReady,
      tabIcon, activeProjectName, exportWorkspace, exportWorkers, exportWorker, exportWorkerGroup, exportAll, importWorkspace, importWorkers, importAll, openCommitDiffFromTicket,
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
    this.$nextTick(() => renderLucideIcons(this.$el));
  },
  template: `
    <div class="app-container">
      <TopToolbar
        :project-name="activeProjectName"
        :project-path="state.workspace"
        :deploy-label="state.config.deploy_label"
        :connected="connected"
        :themes="themeOptions"
        :active-theme="currentTheme"
        :ambient-presets="ambientPresets"
        :ambient-preset="currentAmbientPreset"
        :ambient-volume="currentAmbientVolume"
        :provider-colors="currentProviderColors"
        :default-provider-colors="defaultProviderColors"
        :worker-automation-paused="state.config.worker_automation_paused === true"
        :worker-minimap-collapsed="workerMinimapCollapsed"
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
        @pause-automation="pauseAutomation"
        @resume-automation="resumeAutomation"
        @stop-the-line="stopTheLine"
        @pause-all-automation="pauseAllAutomation"
        @resume-all-automation="resumeAllAutomation"
        @stop-all-lines="stopAllLines"
        @set-worker-minimap-collapsed="setWorkerMinimapCollapsed"
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
          :projects-root="projectSettings.projectsRoot"
          :active-workspace-id="activeWorkspaceId"
          :workspaces="workspaces"
          :multiple-workspaces="multipleWorkspaces"
          @new-task="showCreateModal = true"
          @select-task="selectTask"
          @switch-workspace="switchWorkspace"
          @add-project="addProject"
          @new-project="newProject"
          @clone-project="cloneProject"
          @remove-project="removeProject"
          @configure-worker="configureSlot = $event"
          @open-focus="openFocusTab"
          @transfer-worker="openTransfer"
          @copy-worker="copyWorkerFromLeftPane"
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
                <span v-if="tab.isTerminal" class="tab-close" @click.stop="closeTerminalTab(tab.id)">&times;</span>
              </button>
              <button v-if="activeWorkspaceId" class="tab-btn tab-btn-add" @click="addLiveAgentTab" title="Add Live Agent tab">+</button>
              <button v-if="activeWorkspaceId" class="tab-btn tab-btn-add tab-btn-terminal-add" @click="addTerminalTab" title="New terminal" aria-label="New terminal">
                <i data-lucide="terminal" aria-hidden="true"></i>
              </button>
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
              v-if="activeWorkspaceId && activeTab === 'tasks'"
              :tasks="visibleTicketTasks"
              :columns="state.config.columns"
              :layout="state.layout"
              :view-mode="ticketsViewMode"
              :list-scope="ticketListScope"
              @select-task="selectTask"
              @move-task="moveTask"
              @move-column-tasks="moveColumnTasks"
              @update-task="updateTask"
              @archive-column-tasks="archiveColumnTasks"
              @new-task="showCreateModal = true"
              @update-list-scope="setTicketListScope"
              @update-shown-count="setTicketListShownCount"
            />
            <BullpenTab
              v-if="activeWorkspaceId && activeTab === 'workers'"
              ref="bullpenTabRef"
              :layout="state.layout"
              :config="state.config"
              :profiles="state.profiles"
              :tasks="state.tasks"
              :task-by-id="taskById"
              :workspace="state.workspace"
              :workspace-id="activeWorkspaceId"
              :multiple-workspaces="multipleWorkspaces"
              :minimap-collapsed="workerMinimapCollapsed"
              @add-worker="addWorker"
              @configure-worker="configureSlot = $event"
              @select-task="selectTask"
              @open-focus="openFocusTab"
              @transfer-worker="openTransfer"
              @set-minimap-collapsed="setWorkerMinimapCollapsed"
            />
            <FilesTab v-if="activeWorkspaceId && activeTab === 'files'" :files-version="state.filesVersion" :workspace-id="activeWorkspaceId" :active-theme="currentTheme" :key="'files-' + (activeWorkspaceId || 'none')" />
            <StatsTab
              v-if="activeWorkspaceId && activeTab === 'stats'"
              :tasks="state.tasks"
              :archived-tasks="workspaces[activeWorkspaceId]?.archivedTasks || []"
              :columns="state.config.columns"
              :layout="state.layout"
              :workspace-id="activeWorkspaceId"
              @select-task="selectTask"
            />
            <CommitsTab
              v-if="activeWorkspaceId && activeTab === 'commits'"
              :workspace-id="activeWorkspaceId"
              :open-diff-hash="requestedCommitDiffHash"
              @handled-open-diff-hash="requestedCommitDiffHash = ''"
              :key="'commits-' + (activeWorkspaceId || 'none')"
            />
            <LiveAgentChatTab
              v-for="ct in chatTabs"
              v-show="activeTab === ct.id && ct.workspaceId === activeWorkspaceId"
              :key="ct.workspaceId + ':' + ct.id"
              :session-id="ct.sessionId"
              :workspace-id="ct.workspaceId"
              :last-ai-selection="globalSettings.last_ai_selection"
            />
            <TerminalTab
              v-for="tt in terminalTabs"
              v-show="activeTab === tt.id"
              :key="tt.id"
              :ref="el => setTerminalRef(tt.id, el)"
              :terminal="tt"
              :active="activeTab === tt.id"
              :workspace-id="tt.workspaceId"
              @terminal-input="sendTerminalInput"
              @terminal-resize="resizeTerminal"
              @restart-terminal="restartTerminal"
              @ready="onTerminalReady"
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
        :provider-colors="currentProviderColors"
        :default-provider-colors="defaultProviderColors"
        :active-workspace-id="activeWorkspaceId"
        :last-ai-selection="globalSettings.last_ai_selection"
        @close="closeWorkerConfig"
        @save="saveWorkerConfig"
        @remove="removeWorker"
        @save-profile="saveProfile"
      />
      <WorkerTransferModal
        :visible="transferSlot !== null"
        :worker="transferSlot !== null ? state.layout.slots?.[transferSlot] : null"
        :slot-index="transferSlot"
        :slot-indices="transferSlots"
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
