const { createApp, reactive, ref, computed } = Vue;

const app = createApp({
  components: {
    TopToolbar,
    LeftPane,
    KanbanTab,
    BullpenTab,
    FilesTab,
    TaskCreateModal,
    TaskDetailPanel,
    WorkerConfigModal,
    ToastContainer,
  },
  setup() {
    // Per-workspace backing store (not directly rendered)
    const workspaces = reactive({});  // workspaceId -> { workspace, config, layout, tasks, profiles, teams, filesVersion, unseenActivity }

    // Active view state — mirrors whichever workspace is active
    const state = reactive({
      workspace: '',
      config: { name: 'Bullpen', grid: { rows: 4, cols: 6 }, columns: [] },
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
        config: { name: 'Bullpen', grid: { rows: 4, cols: 6 }, columns: [] },
        layout: { slots: [] },
        tasks: [],
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

    function _isActive(wsId) {
      return wsId === activeWorkspaceId.value;
    }

    function switchWorkspace(wsId) {
      if (!workspaces[wsId]) return;
      activeWorkspaceId.value = wsId;
      workspaces[wsId].unseenActivity = 0;
      _syncToView(wsId);
      document.title = state.config.name || 'Bullpen';
    }

    const connected = ref(false);
    const activeTab = ref('tasks');
    const leftPaneVisible = ref(true);
    const toasts = reactive([]);
    const showCreateModal = ref(false);
    const selectedTaskId = ref(null);
    const configureSlot = ref(null);

    // Worker Focus Mode state
    const outputBuffers = reactive({});  // keyed by slot index
    const focusTabs = reactive([]);      // [{slotIndex, workspaceId, label}]
    let toastId = 0;

    const selectedTask = computed(() => {
      if (!selectedTaskId.value) return null;
      return state.tasks.find(t => t.id === selectedTaskId.value) || null;
    });

    const configureWorkerData = computed(() => {
      if (configureSlot.value === null) return null;
      return state.layout?.slots?.[configureSlot.value] || null;
    });

    // Socket.io
    const socket = io();

    socket.on('connect', () => { connected.value = true; });
    socket.on('disconnect', () => { connected.value = false; });

    socket.on('state:init', (data) => {
      const wsId = data.workspaceId;
      const ws = _getWs(wsId);
      ws.workspace = data.workspace;
      ws.config = data.config;
      ws.layout = data.layout;
      ws.tasks = data.tasks;
      ws.profiles = data.profiles || [];
      ws.teams = data.teams || [];

      // First workspace becomes active
      if (!activeWorkspaceId.value) {
        activeWorkspaceId.value = wsId;
      }

      if (_isActive(wsId)) {
        _syncToView(wsId);
        document.title = state.config.name || 'Bullpen';
      }
    });

    socket.on('task:created', (task) => {
      const wsId = task.workspaceId || activeWorkspaceId.value;
      const ws = _getWs(wsId);
      ws.tasks.push(task);
      if (!_isActive(wsId)) ws.unseenActivity++;
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
      ws.config = config;
      if (_isActive(wsId)) state.config = config;
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
    socket.on('worker:output', (data) => {
      const slot = data.slot;
      if (!outputBuffers[slot]) outputBuffers[slot] = [];
      outputBuffers[slot].push(...data.lines);
      // Cap at 5000 lines client-side
      if (outputBuffers[slot].length > 5000) {
        outputBuffers[slot].splice(0, outputBuffers[slot].length - 5000);
      }
    });
    socket.on('worker:output:catchup', (data) => {
      const slot = data.slot;
      outputBuffers[slot] = data.lines || [];
    });

    // Helper to attach workspaceId to outgoing events
    function _wsData(data) {
      return { ...data, workspaceId: activeWorkspaceId.value };
    }

    // Task actions
    function createTask(data) { socket.emit('task:create', _wsData(data)); }
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
      // Clear stale buffer and request catchup
      outputBuffers[slotIndex] = outputBuffers[slotIndex] || [];
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

    const allTabs = computed(() => {
      const tabs = [
        { id: 'tasks', label: 'Tasks' },
        { id: 'workers', label: 'Workers' },
        { id: 'files', label: 'Files' },
      ];
      for (const ft of focusTabs) {
        tabs.push({ id: 'focus-' + ft.slotIndex, label: ft.label, isFocus: true, slotIndex: ft.slotIndex });
      }
      return tabs;
    });

    // Config/team actions
    function updateConfig(data) { socket.emit('config:update', _wsData(data)); }
    function saveTeam(name) { socket.emit('team:save', _wsData({ name })); }
    function loadTeam(name) { socket.emit('team:load', _wsData({ name })); }
    function saveProfile(data) { socket.emit('profile:create', _wsData(data)); }

    // Project actions
    function addProject(path) { socket.emit('project:add', { path }); }
    function removeProject(wsId) { socket.emit('project:remove', { workspaceId: wsId }); }

    function toggleLeftPane() { leftPaneVisible.value = !leftPaneVisible.value; }

    // Theme
    const PRISM_DARK = 'https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css';
    const PRISM_LIGHT = 'https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism.min.css';
    (function initTheme() {
      const saved = localStorage.getItem('bullpen-theme');
      if (saved) document.documentElement.setAttribute('data-theme', saved);
    })();
    function toggleTheme() {
      const isLight = document.documentElement.getAttribute('data-theme') === 'light';
      const next = isLight ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('bullpen-theme', next);
      const prismLink = document.getElementById('prism-theme');
      if (prismLink) prismLink.href = next === 'light' ? PRISM_LIGHT : PRISM_DARK;
    }

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
      addProject, removeProject,
      connected, activeTab, leftPaneVisible, toasts,
      showCreateModal, selectedTask, configureSlot, configureWorkerData,
      toggleLeftPane, toggleTheme, createTask, updateTask, deleteTask, archiveTask, archiveDone, clearTaskOutput,
      moveTask, selectTask, addWorker, removeWorker, moveWorker,
      saveWorkerConfig, assignTask, startWorkerSlot,
      stopWorkerSlot, updateConfig, saveTeam, loadTeam, saveProfile, addToast, dismissToast,
      gridOptions, onTabBarGridResize, duplicateWorker,
      outputBuffers, focusTabs, openFocusTab, closeFocusTab, focusTask, allTabs,
    };
  },
  template: `
    <div class="app-container">
      <TopToolbar
        :name="state.config.name"
        :connected="connected"
        @toggle-left-pane="toggleLeftPane"
        @toggle-theme="toggleTheme"
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
          @new-task="showCreateModal = true"
          @select-task="selectTask"
          @switch-workspace="switchWorkspace"
          @add-project="addProject"
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
                <span v-if="tab.isFocus" class="focus-dot"></span>
                {{ tab.label }}
                <span v-if="tab.isFocus" class="tab-close" @click.stop="closeFocusTab(tab.slotIndex)">&times;</span>
              </button>
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
              :tasks="state.tasks"
              :columns="state.config.columns"
              :layout="state.layout"
              @select-task="selectTask"
              @move-task="moveTask"
              @archive-done="archiveDone"
            />
            <BullpenTab
              v-if="activeTab === 'workers'"
              :layout="state.layout"
              :config="state.config"
              :profiles="state.profiles"
              :tasks="state.tasks"
              :workspace="state.workspace"
              @add-worker="addWorker"
              @configure-worker="configureSlot = $event"
              @select-task="selectTask"
              @open-focus="openFocusTab"
            />
            <FilesTab v-if="activeTab === 'files'" :files-version="state.filesVersion" />
            <WorkerFocusView
              v-for="ft in focusTabs"
              v-show="activeTab === 'focus-' + ft.slotIndex"
              :key="'focus-' + ft.slotIndex"
              :worker="state.layout?.slots?.[ft.slotIndex]"
              :slot-index="ft.slotIndex"
              :task="focusTask(ft.slotIndex)"
              :output-lines="outputBuffers[ft.slotIndex] || []"
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
      <ToastContainer :toasts="toasts" @dismiss="dismissToast" />
    </div>
  `
});

app.mount('#app');
