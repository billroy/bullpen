const LeftPane = {
  props: ['tasks', 'layout', 'visible'],
  emits: ['new-task', 'select-task'],
  template: `
    <div class="left-pane" :class="{ collapsed: !visible }">
      <div class="left-pane-section">
        <div class="section-header">
          <h3>Inbox</h3>
          <button class="btn btn-sm" @click="$emit('new-task')">+ New Task</button>
        </div>
        <div class="inbox-list">
          <div v-if="inboxTasks.length === 0" class="empty-state">No tasks in inbox</div>
          <div v-for="task in inboxTasks" :key="task.id"
               class="inbox-item"
               draggable="true"
               @dragstart="onDragStart($event, task.id)"
               @click="$emit('select-task', task.id)">
            <span class="inbox-title">{{ task.title }}</span>
            <span class="badge" :class="'priority-' + (task.priority || 'normal')">{{ task.priority || 'normal' }}</span>
          </div>
        </div>
      </div>
      <div class="left-pane-section">
        <div class="section-header">
          <h3>Workers</h3>
        </div>
        <div class="worker-roster">
          <div v-if="!workerList.length" class="empty-state">No workers configured</div>
          <div v-for="w in workerList" :key="w.slot"
               class="roster-item"
               :class="{ 'drag-over': rosterDragSlot === w.slot }"
               :style="{ borderLeftColor: agentColor(w.agent) }"
               @dragover.prevent="onRosterDragOver($event, w)"
               @dragleave="onRosterDragLeave"
               @drop="onRosterDrop($event, w.slot)">
            <span class="roster-dot" :class="'status-' + (w.state || 'idle')"></span>
            <span class="roster-name">{{ w.name }}</span>
            <span class="agent-badge" :style="{ color: agentColor(w.agent) }">{{ w.agent }}</span>
          </div>
        </div>
      </div>
    </div>
  `,
  computed: {
    inboxTasks() {
      const weight = { urgent: 0, high: 1, normal: 2, low: 3 };
      return (this.tasks || [])
        .filter(t => t.status === 'inbox')
        .sort((a, b) => {
          const pa = weight[a.priority] ?? weight.normal;
          const pb = weight[b.priority] ?? weight.normal;
          if (pa !== pb) return pa - pb;
          return (b.created_at || '').localeCompare(a.created_at || '');
        });
    },
    workerList() {
      if (!this.layout?.slots) return [];
      return this.layout.slots
        .map((s, i) => s ? { slot: i, name: s.name, state: s.state || 'idle', agent: s.agent } : null)
        .filter(Boolean);
    }
  },
  data() {
    return { rosterDragSlot: null };
  },
  methods: {
    onDragStart(e, taskId) {
      e.dataTransfer.setData('text/plain', taskId);
      e.dataTransfer.effectAllowed = 'move';
    },
    agentColor(agent) {
      return { claude: '#da7756', codex: '#10a37f' }[agent] || '#6B7280';
    },
    onRosterDragOver(e, w) {
      if (e.dataTransfer.types.includes('text/plain')) {
        e.dataTransfer.dropEffect = 'move';
        this.rosterDragSlot = w.slot;
      }
    },
    onRosterDragLeave() {
      this.rosterDragSlot = null;
    },
    onRosterDrop(e, slot) {
      this.rosterDragSlot = null;
      const taskId = e.dataTransfer.getData('text/plain');
      if (taskId) {
        this.$root.assignTask(taskId, slot);
      }
    }
  }
};
