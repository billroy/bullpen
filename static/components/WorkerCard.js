const WorkerCard = {
  props: ['worker', 'slotIndex'],
  emits: ['configure', 'remove'],
  template: `
    <div class="worker-card"
         draggable="true"
         @dragstart="onDragStart"
         @dragover.prevent="onDragOver"
         @dragleave="onDragLeave"
         @drop="onDrop">
      <div class="worker-card-header" :style="{ background: agentColor }">
        <span class="worker-card-name" :title="worker.name">{{ worker.name }}</span>
        <button class="worker-card-edit" @click.stop="$emit('configure', slotIndex)" title="Configure">&#9998;</button>
      </div>
      <div class="worker-card-body">
        <div class="worker-card-status">
          <span class="status-pill" :class="'status-' + (worker.state || 'idle')">
            {{ (worker.state || 'idle').toUpperCase() }}
          </span>
          <span class="worker-card-agent">{{ worker.agent }}/{{ worker.model }}</span>
        </div>
        <div class="worker-card-queue" v-if="worker.task_queue && worker.task_queue.length">
          <div v-for="taskId in worker.task_queue" :key="taskId" class="worker-queue-item">
            {{ taskId }}
          </div>
        </div>
        <div v-else class="worker-card-empty">No tasks queued</div>
      </div>
    </div>
  `,
  computed: {
    agentColor() {
      const colors = {
        claude: '#da7756',
        codex: '#10a37f',
      };
      return colors[this.worker.agent] || '#6B7280';
    }
  },
  methods: {
    onDragStart(e) {
      e.dataTransfer.setData('application/x-worker-slot', String(this.slotIndex));
      e.dataTransfer.effectAllowed = 'move';
    },
    onDragOver(e) {
      // Accept worker drags for reorder
      if (e.dataTransfer.types.includes('application/x-worker-slot')) {
        e.currentTarget.classList.add('drag-over');
      }
    },
    onDragLeave(e) {
      e.currentTarget.classList.remove('drag-over');
    },
    onDrop(e) {
      e.currentTarget.classList.remove('drag-over');
      const fromSlot = e.dataTransfer.getData('application/x-worker-slot');
      if (fromSlot !== '' && Number(fromSlot) !== this.slotIndex) {
        this.$root.moveWorker(Number(fromSlot), this.slotIndex);
      }
    }
  }
};
