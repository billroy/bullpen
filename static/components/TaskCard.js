const TaskCard = {
  props: ['task'],
  emits: ['select-task'],
  template: `
    <div class="task-card"
         draggable="true"
         @dragstart="onDragStart"
         @click="$emit('select-task', task.id)">
      <div class="task-card-title">{{ task.title }}</div>
      <div class="task-card-meta">
        <span class="badge" :class="'priority-' + (task.priority || 'normal')">{{ task.priority || 'normal' }}</span>
        <span class="badge type-badge">{{ task.type || 'task' }}</span>
      </div>
    </div>
  `,
  methods: {
    onDragStart(e) {
      e.dataTransfer.setData('text/plain', this.task.id);
      e.dataTransfer.effectAllowed = 'move';
    }
  }
};
