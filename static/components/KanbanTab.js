const KanbanTab = {
  props: ['tasks', 'columns'],
  emits: ['select-task', 'move-task'],
  components: { TaskCard },
  template: `
    <div class="kanban-board">
      <div v-for="col in columns" :key="col.key" class="kanban-column"
           @dragover.prevent="onDragOver($event, col.key)"
           @dragleave="onDragLeave($event)"
           @drop="onDrop($event, col.key)">
        <div class="kanban-column-header" :style="{ borderTopColor: col.color }">
          <span class="column-label">{{ col.label }}</span>
          <span class="column-count">{{ columnTasks(col.key).length }}</span>
        </div>
        <div class="kanban-column-body">
          <div v-if="columnTasks(col.key).length === 0" class="empty-state kanban-drop-zone">—</div>
          <TaskCard
            v-for="task in columnTasks(col.key)"
            :key="task.id"
            :task="task"
            @select-task="$emit('select-task', $event)"
          />
        </div>
      </div>
    </div>
  `,
  methods: {
    columnTasks(key) {
      const weight = { urgent: 0, high: 1, normal: 2, low: 3 };
      return (this.tasks || [])
        .filter(t => t.status === key)
        .sort((a, b) => {
          const pa = weight[a.priority] ?? weight.normal;
          const pb = weight[b.priority] ?? weight.normal;
          if (pa !== pb) return pa - pb;
          return (a.order || '').localeCompare(b.order || '');
        });
    },
    onDragOver(e, colKey) {
      e.dataTransfer.dropEffect = 'move';
      e.currentTarget.classList.add('drag-over');
    },
    onDragLeave(e) {
      e.currentTarget.classList.remove('drag-over');
    },
    onDrop(e, colKey) {
      e.currentTarget.classList.remove('drag-over');
      const taskId = e.dataTransfer.getData('text/plain');
      if (taskId) {
        this.$emit('move-task', { id: taskId, status: colKey });
      }
    }
  }
};
