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

    // Task actions
    function createTask(data) { socket.emit('task:create', data); }
    function updateTask(data) { socket.emit('task:update', data); }
    function deleteTask(id) { socket.emit('task:delete', { id }); }
    function clearTaskOutput(id) { socket.emit('task:clear_output', { id }); }
    function moveTask({ id, status }) { socket.emit('task:update', { id, status }); }
    function selectTask(id) { selectedTaskId.value = id; }

    // Worker actions
    function addWorker({ slot, profile }) { socket.emit('worker:add', { slot, profile }); }
    function removeWorker(slot) { socket.emit('worker:remove', { slot }); }
    function moveWorker(from, to) { socket.emit('worker:move', { from, to }); }
    function configureWorker(slot, fields) { socket.emit('worker:configure', { slot, fields }); }
    function saveWorkerConfig({ slot, fields }) { socket.emit('worker:configure', { slot, fields }); }

    // Config/team actions
    function updateConfig(data) { socket.emit('config:update', data); }
    function saveTeam(name) { socket.emit('team:save', { name }); }
    function loadTeam(name) { socket.emit('team:load', { name }); }
    function saveProfile(data) { socket.emit('profile:create', data); }

    function toggleLeftPane() { leftPaneVisible.value = !leftPaneVisible.value; }

    function addToast(message, type = 'info') {
      const id = ++toastId;
      toasts.push({ id, message, type });
      if (type !== 'error') {
        setTimeout(() => {
          const idx = toasts.findIndex(t => t.id === id);
          if (idx >= 0) toasts.splice(idx, 1);
        }, 5000);
      }
    }

    return {
      state, connected, activeTab, leftPaneVisible, toasts,
      showCreateModal, selectedTask, configureSlot, configureWorkerData,
      toggleLeftPane, createTask, updateTask, deleteTask, clearTaskOutput,
      moveTask, selectTask, addWorker, removeWorker, moveWorker,
      configureWorker, saveWorkerConfig, updateConfig, saveTeam, loadTeam,
      saveProfile, addToast,
    };
  },
  template: `
    <div class="app-container">
      <TopToolbar
        :workspace="state.workspace"
        :name="state.config.name"
        :connected="connected"
        @toggle-left-pane="toggleLeftPane"
      />
      <div class="app-body">
        <LeftPane
          :tasks="state.tasks"
          :visible="leftPaneVisible"
          @new-task="showCreateModal = true"
          @select-task="selectTask"
        />
        <div class="main-pane">
          <div class="tab-bar">
            <button
              v-for="tab in ['kanban', 'bullpen', 'files']"
              :key="tab"
              class="tab-btn"
              :class="{ active: activeTab === tab }"
              @click="activeTab = tab"
            >{{ tab.charAt(0).toUpperCase() + tab.slice(1) }}</button>
          </div>
          <div class="tab-content">
            <KanbanTab
              v-if="activeTab === 'kanban'"
              :tasks="state.tasks"
              :columns="state.config.columns"
              @select-task="selectTask"
              @move-task="moveTask"
            />
            <BullpenTab
              v-if="activeTab === 'bullpen'"
              :layout="state.layout"
              :config="state.config"
              :profiles="state.profiles"
              @add-worker="addWorker"
              @configure-worker="configureSlot = $event"
            />
            <FilesTab v-if="activeTab === 'files'" />
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
      <ToastContainer :toasts="toasts" />
    </div>
  `
});

app.mount('#app');
