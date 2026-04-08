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
    const state = reactive({
      workspace: '',
      config: { name: 'Bullpen', grid: { rows: 4, cols: 6 }, columns: [] },
      layout: { slots: [] },
      tasks: [],
      profiles: [],
      teams: [],
      filesVersion: 0,
    });

    const connected = ref(false);
    const activeTab = ref('kanban');
    const leftPaneVisible = ref(true);
    const toasts = reactive([]);
    const showCreateModal = ref(false);
    const selectedTaskId = ref(null);
    const configureSlot = ref(null);
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
      state.workspace = data.workspace;
      state.config = data.config;
      state.layout = data.layout;
      state.tasks = data.tasks;
      state.profiles = data.profiles || [];
      state.teams = data.teams || [];
      document.title = state.config.name || 'Bullpen';
    });

    socket.on('task:created', (task) => { state.tasks.push(task); });
    socket.on('task:updated', (task) => {
      const idx = state.tasks.findIndex(t => t.id === task.id);
      if (idx >= 0) state.tasks[idx] = task;
      else state.tasks.push(task);
    });
    socket.on('task:deleted', (data) => {
      state.tasks = state.tasks.filter(t => t.id !== data.id);
      if (selectedTaskId.value === data.id) selectedTaskId.value = null;
    });

    socket.on('layout:updated', (layout) => { state.layout = layout; });
    socket.on('config:updated', (config) => { state.config = config; });
    socket.on('profiles:updated', (profiles) => { state.profiles = profiles; });
    socket.on('teams:updated', (teams) => { state.teams = teams; });
    socket.on('error', (data) => { addToast(data.message, 'error'); });
    socket.on('files:changed', () => { state.filesVersion++; });

    // Task actions
    function createTask(data) { socket.emit('task:create', data); }
    function updateTask(data) { socket.emit('task:update', data); }
    function deleteTask(id) {
      const task = state.tasks.find(t => t.id === id);
      if (task && (task.status === 'assigned' || task.status === 'in-progress')) {
        if (!confirm(`Task "${task.title}" is ${task.status}. Delete anyway?`)) return;
      }
      socket.emit('task:delete', { id });
    }
    function clearTaskOutput(id) { socket.emit('task:clear_output', { id }); }
    function moveTask({ id, status }) { socket.emit('task:update', { id, status }); }
    function selectTask(id) { selectedTaskId.value = id; }

    // Worker actions
    function addWorker({ slot, profile }) { socket.emit('worker:add', { slot, profile }); }
    function removeWorker(slot) {
      const worker = state.layout?.slots?.[slot];
      if (worker?.task_queue?.length) {
        if (!confirm(`Worker "${worker.name}" has ${worker.task_queue.length} task(s) queued. Remove anyway?`)) return;
      }
      socket.emit('worker:remove', { slot });
    }
    function moveWorker(from, to) { socket.emit('worker:move', { from, to }); }
    function saveWorkerConfig({ slot, fields }) { socket.emit('worker:configure', { slot, fields }); }

    // Execution actions
    function assignTask(taskId, slot) { socket.emit('task:assign', { task_id: taskId, slot }); }
    function startWorkerSlot(slot) { socket.emit('worker:start', { slot }); }
    function stopWorkerSlot(slot) { socket.emit('worker:stop', { slot }); }

    // Config/team actions
    function updateConfig(data) { socket.emit('config:update', data); }
    function saveTeam(name) { socket.emit('team:save', { name }); }
    function loadTeam(name) { socket.emit('team:load', { name }); }
    function saveProfile(data) { socket.emit('profile:create', data); }

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
      state, connected, activeTab, leftPaneVisible, toasts,
      showCreateModal, selectedTask, configureSlot, configureWorkerData,
      toggleLeftPane, toggleTheme, createTask, updateTask, deleteTask, clearTaskOutput,
      moveTask, selectTask, addWorker, removeWorker, moveWorker,
      saveWorkerConfig, assignTask, startWorkerSlot,
      stopWorkerSlot, updateConfig, saveTeam, loadTeam, saveProfile, addToast, dismissToast,
      gridOptions, onTabBarGridResize,
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
          :visible="leftPaneVisible"
          @new-task="showCreateModal = true"
          @select-task="selectTask"
        />
        <div class="main-pane">
          <div class="tab-bar">
            <div class="tab-bar-left">
              <button
                v-for="tab in ['kanban', 'bullpen', 'files']"
                :key="tab"
                class="tab-btn"
                :class="{ active: activeTab === tab }"
                @click="activeTab = tab"
              >{{ tab.charAt(0).toUpperCase() + tab.slice(1) }}</button>
            </div>
            <div v-if="activeTab === 'bullpen'" class="tab-bar-right">
              <span class="bullpen-path" :title="state.workspace">{{ state.workspace ? state.workspace.split('/').slice(-2).join('/') : '' }}</span>
              <select class="form-select" :value="(state.config.grid?.rows || 4) + 'x' + (state.config.grid?.cols || 6)" @change="onTabBarGridResize">
                <option v-for="opt in gridOptions" :key="opt" :value="opt">{{ opt }}</option>
              </select>
            </div>
          </div>
          <div class="tab-content">
            <KanbanTab
              v-if="activeTab === 'kanban'"
              :tasks="state.tasks"
              :columns="state.config.columns"
              :layout="state.layout"
              @select-task="selectTask"
              @move-task="moveTask"
            />
            <BullpenTab
              v-if="activeTab === 'bullpen'"
              :layout="state.layout"
              :config="state.config"
              :profiles="state.profiles"
              :tasks="state.tasks"
              :workspace="state.workspace"
              @add-worker="addWorker"
              @configure-worker="configureSlot = $event"
              @select-task="selectTask"
            />
            <FilesTab v-if="activeTab === 'files'" :files-version="state.filesVersion" />
          </div>
        </div>
        <TaskDetailPanel
          :task="selectedTask"
          :columns="state.config.columns"
          @close="selectTask(null)"
          @update="updateTask"
          @delete="deleteTask"
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
