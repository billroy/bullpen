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
    ToastContainer,
  },
  setup() {
    const state = reactive({
      workspace: '',
      config: { name: 'Bullpen', grid: { rows: 4, cols: 6 }, columns: [] },
      layout: { slots: [] },
      tasks: [],
    });

    const connected = ref(false);
    const activeTab = ref('kanban');
    const leftPaneVisible = ref(true);
    const toasts = reactive([]);
    const showCreateModal = ref(false);
    const selectedTaskId = ref(null);
    let toastId = 0;

    const selectedTask = computed(() => {
      if (!selectedTaskId.value) return null;
      return state.tasks.find(t => t.id === selectedTaskId.value) || null;
    });

    // Socket.io connection
    const socket = io();

    socket.on('connect', () => { connected.value = true; });
    socket.on('disconnect', () => { connected.value = false; });

    socket.on('state:init', (data) => {
      state.workspace = data.workspace;
      state.config = data.config;
      state.layout = data.layout;
      state.tasks = data.tasks;
    });

    socket.on('task:created', (task) => {
      state.tasks.push(task);
    });

    socket.on('task:updated', (task) => {
      const idx = state.tasks.findIndex(t => t.id === task.id);
      if (idx >= 0) {
        state.tasks[idx] = task;
      } else {
        state.tasks.push(task);
      }
    });

    socket.on('task:deleted', (data) => {
      state.tasks = state.tasks.filter(t => t.id !== data.id);
      if (selectedTaskId.value === data.id) {
        selectedTaskId.value = null;
      }
    });

    socket.on('error', (data) => {
      addToast(data.message, 'error');
    });

    // Actions
    function createTask(data) {
      socket.emit('task:create', data);
    }

    function updateTask(data) {
      socket.emit('task:update', data);
    }

    function deleteTask(id) {
      socket.emit('task:delete', { id });
    }

    function clearTaskOutput(id) {
      socket.emit('task:clear_output', { id });
    }

    function moveTask({ id, status }) {
      socket.emit('task:update', { id, status });
    }

    function selectTask(id) {
      selectedTaskId.value = id;
    }

    function toggleLeftPane() {
      leftPaneVisible.value = !leftPaneVisible.value;
    }

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
      state,
      connected,
      activeTab,
      leftPaneVisible,
      toasts,
      showCreateModal,
      selectedTask,
      toggleLeftPane,
      createTask,
      updateTask,
      deleteTask,
      clearTaskOutput,
      moveTask,
      selectTask,
      addToast,
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
      <ToastContainer :toasts="toasts" />
    </div>
  `
});

app.mount('#app');
