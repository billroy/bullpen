const WorkerCard = {
  props: ['worker', 'slotIndex', 'tasks'],
  emits: ['configure'],
  template: `
    <div class="worker-card" :class="{ 'drag-over': dragOver }"
         draggable="true"
         @dragstart="onDragStart"
         @dragover.prevent="onDragOver"
         @dragleave="onDragLeave"
         @drop="onDrop">
      <div class="worker-card-header" :style="{ background: agentColor }">
        <span class="worker-card-name" :title="worker.name">{{ worker.name }}</span>
        <div class="worker-card-actions">
          <button v-if="canStart" class="worker-action-btn start-btn" @click.stop="startWorker" title="Start">&#9654;</button>
          <button v-if="isWorking" class="worker-action-btn stop-btn" @click.stop="stopWorker" title="Stop">&#9632;</button>
          <button class="worker-card-edit" @click.stop="$emit('configure', slotIndex)" title="Configure">&#9998;</button>
        </div>
      </div>
      <div class="worker-card-body">
        <div class="worker-card-status">
          <span class="status-pill" :class="'status-' + workerState">
            {{ workerState.toUpperCase() }}
          </span>
          <span class="worker-card-agent">{{ worker.agent }}/{{ worker.model }}</span>
        </div>
        <div class="worker-card-queue" v-if="queuedTasks.length">
          <div v-for="t in queuedTasks" :key="t.id" class="worker-queue-item" :title="t.title">
            {{ t.title }}
          </div>
        </div>
        <div v-else class="worker-card-empty">No tasks queued</div>
        <div v-if="isWorking && lastOutput" class="worker-card-output">
          <pre>{{ lastOutput }}</pre>
        </div>
      </div>
    </div>
  `,
  data() {
    return { dragOver: false };
  },
  computed: {
    workerState() { return this.worker.state || 'idle'; },
    isWorking() { return this.workerState === 'working'; },
    canStart() {
      return this.workerState === 'idle' && this.worker.task_queue && this.worker.task_queue.length > 0;
    },
    agentColor() {
      return { claude: '#da7756', codex: '#10a37f' }[this.worker.agent] || '#6B7280';
    },
    queuedTasks() {
      if (!this.worker.task_queue || !this.tasks) return [];
      return this.worker.task_queue.map(id => {
        const t = this.tasks.find(task => task.id === id);
        return t || { id, title: id };
      });
    },
    lastOutput() {
      // Show last few lines of the first task's agent output if working
      if (!this.worker.task_queue?.length || !this.tasks) return '';
      const task = this.tasks.find(t => t.id === this.worker.task_queue[0]);
      if (!task?.body) return '';
      const marker = '## Agent Output';
      const idx = task.body.indexOf(marker);
      if (idx < 0) return '';
      const output = task.body.substring(idx + marker.length).trim();
      const lines = output.split('\\n');
      return lines.slice(-20).join('\\n');
    }
  },
  methods: {
    onDragStart(e) {
      e.dataTransfer.setData('application/x-worker-slot', String(this.slotIndex));
      e.dataTransfer.effectAllowed = 'move';
    },
    onDragOver(e) {
      if (e.dataTransfer.types.includes('text/plain')) {
        e.dataTransfer.dropEffect = 'move';
        this.dragOver = true;
      }
    },
    onDragLeave() { this.dragOver = false; },
    onDrop(e) {
      this.dragOver = false;
      const taskId = e.dataTransfer.getData('text/plain');
      if (taskId) {
        this.$root.assignTask(taskId, this.slotIndex);
      }
    },
    startWorker() {
      this.$root.startWorkerSlot(this.slotIndex);
    },
    stopWorker() {
      this.$root.stopWorkerSlot(this.slotIndex);
    }
  }
};
