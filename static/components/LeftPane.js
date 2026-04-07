const LeftPane = {
  props: ['tasks', 'visible'],
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
          <div class="empty-state">No workers configured</div>
        </div>
      </div>
    </div>
  `,
  computed: {
    inboxTasks() {
      return (this.tasks || [])
        .filter(t => t.status === 'inbox')
        .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
    }
  }
};
