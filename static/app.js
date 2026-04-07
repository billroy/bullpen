const { createApp, reactive, ref } = Vue;

const app = createApp({
  components: {
    TopToolbar,
    LeftPane,
    KanbanTab,
    BullpenTab,
    FilesTab,
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

    // Socket.io connection
    const socket = io();

    socket.on('connect', () => {
      connected.value = true;
    });

    socket.on('disconnect', () => {
      connected.value = false;
    });

    socket.on('state:init', (data) => {
      state.workspace = data.workspace;
      state.config = data.config;
      state.layout = data.layout;
      state.tasks = data.tasks;
    });

    function toggleLeftPane() {
      leftPaneVisible.value = !leftPaneVisible.value;
    }

    return {
      state,
      connected,
      activeTab,
      leftPaneVisible,
      toasts,
      toggleLeftPane,
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
            />
            <BullpenTab
              v-if="activeTab === 'bullpen'"
              :layout="state.layout"
              :config="state.config"
            />
            <FilesTab v-if="activeTab === 'files'" />
          </div>
        </div>
      </div>
      <ToastContainer :toasts="toasts" />
    </div>
  `
});

app.mount('#app');
