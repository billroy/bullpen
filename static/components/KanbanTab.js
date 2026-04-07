const KanbanTab = {
  props: ['tasks', 'columns'],
  template: `
    <div class="kanban-board">
      <div v-for="col in columns" :key="col.key" class="kanban-column">
        <div class="kanban-column-header" :style="{ borderTopColor: col.color }">
          <span class="column-label">{{ col.label }}</span>
          <span class="column-count">{{ columnTasks(col.key).length }}</span>
        </div>
        <div class="kanban-column-body">
          <div v-if="columnTasks(col.key).length === 0" class="empty-state">—</div>
          <div v-for="task in columnTasks(col.key)" :key="task.id"
               class="task-card"
               @click="$emit('select-task', task.id)">
            <div class="task-card-title">{{ task.title }}</div>
            <div class="task-card-meta">
              <span class="badge" :class="'priority-' + (task.priority || 'normal')">{{ task.priority || 'normal' }}</span>
              <span class="badge type-badge">{{ task.type || 'task' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  methods: {
    columnTasks(key) {
      return (this.tasks || [])
        .filter(t => t.status === key)
        .sort((a, b) => (a.order || '').localeCompare(b.order || ''));
    }
  }
};
