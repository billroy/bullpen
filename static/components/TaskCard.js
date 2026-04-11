const TaskCard = {
  props: ['task', 'layout'],
  emits: ['select-task'],
  computed: {
    assignedWorkerName() {
      if (!this.task.assigned_to && this.task.assigned_to !== 0) return null;
      const slot = parseInt(this.task.assigned_to, 10);
      if (isNaN(slot)) return null;
      const worker = this.layout?.slots?.[slot];
      return worker?.name || null;
    }
  },
  template: `
    <div class="task-card"
         draggable="true"
         @dragstart="onDragStart"
         @click="$emit('select-task', task.id)">
      <div class="task-card-title">
        <i class="ticket-type-icon ticket-type-icon--card" data-lucide="tag" aria-hidden="true"></i>
        <span class="task-card-title-text">{{ task.title }}</span>
      </div>
      <div class="task-card-meta">
        <span class="badge" :class="'priority-' + (task.priority || 'normal')">{{ task.priority || 'normal' }}</span>
        <span class="badge type-badge">{{ task.type || 'task' }}</span>
      </div>
      <span v-if="assignedWorkerName" class="task-card-worker">{{ assignedWorkerName }}</span>
    </div>
  `,
  methods: {
    onDragStart(e) {
      e.dataTransfer.setData(window.BULLPEN_TASK_DND_MIME, this.task.id);
      e.dataTransfer.setData('text/plain', this.task.id);
      e.dataTransfer.effectAllowed = 'move';
    }
  }
};
