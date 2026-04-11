const WorkerCard = {
  props: ['worker', 'slotIndex', 'tasks', 'outputLines', 'multipleWorkspaces'],
  emits: ['configure', 'select-task', 'open-focus', 'transfer'],
  template: `
    <div class="worker-card" :class="{ 'drag-over': dragOver }"
         draggable="true"
         @dragstart="onDragStart"
         @dragover.prevent="onDragOver"
         @dragleave="onDragLeave"
         @drop.prevent="onDrop"
>
      <span v-if="passDir === 'up'" class="pass-indicator pass-up" title="This worker passes tickets up" aria-label="This worker passes tickets up">&#x25B2;</span>
      <span v-if="passDir === 'down'" class="pass-indicator pass-down" title="This worker passes tickets down" aria-label="This worker passes tickets down">&#x25BC;</span>
      <span v-if="passDir === 'left'" class="pass-indicator pass-left" title="This worker passes tickets left" aria-label="This worker passes tickets left">&#x25C0;</span>
      <span v-if="passDir === 'right'" class="pass-indicator pass-right" title="This worker passes tickets right" aria-label="This worker passes tickets right">&#x25B6;</span>
      <div class="worker-card-header" :style="{ background: agentColor }" :title="expertiseTooltip || null" @dblclick="$emit('configure', slotIndex)">
        <div class="worker-card-identity">
          <i class="worker-type-icon worker-type-icon--card" :data-lucide="workerIcon" aria-hidden="true"></i>
          <span class="worker-card-name">{{ worker.name }}</span>
        </div>
        <div class="worker-card-actions">
          <button class="worker-menu-btn" ref="menuBtn" @click.stop="toggleMenu" title="Actions">&hellip;</button>
          <div v-if="showMenu" class="worker-menu" :style="menuStyle" @click.stop>
            <button class="worker-menu-item" @click="menuEdit">Edit</button>
            <button v-if="canStart && !isPaused" class="worker-menu-item" @click="menuRun">Run</button>
            <button v-if="isWorking" class="worker-menu-item" @click="menuWatch">Watch</button>
            <button v-if="isWorking" class="worker-menu-item" @click="menuStop">Stop</button>
            <button v-if="isScheduled && !isPaused" class="worker-menu-item" @click="menuPause">Pause</button>
            <button v-if="isScheduled && isPaused" class="worker-menu-item" @click="menuUnpause">Unpause</button>
            <button class="worker-menu-item" @click="menuDuplicate">Duplicate</button>
            <button v-if="multipleWorkspaces" class="worker-menu-item" @click="menuCopyTo">Copy to workspace&hellip;</button>
            <button v-if="multipleWorkspaces && canMove" class="worker-menu-item" @click="menuMoveTo">Move to workspace&hellip;</button>
            <button class="worker-menu-item worker-menu-danger" @click="menuDelete">Delete</button>
          </div>
        </div>
      </div>
      <div class="worker-card-body" @click.stop="onBodyClick" @dblclick.stop="onBodyDblClick">
        <div class="worker-card-status">
          <span class="status-pill" :class="'status-' + workerState">
            {{ isPaused ? 'PAUSED' : workerState.toUpperCase() }}
          </span>
          <span class="worker-card-agent">{{ worker.agent }}/{{ worker.model }}</span>
        </div>
        <div class="worker-card-queue" v-if="queuedTasks.length">
          <div v-for="t in queuedTasks" :key="t.id" class="worker-queue-item" :title="t.title"
               @click.stop="$emit('select-task', t.id)">
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
    return { dragOver: false, showMenu: false, menuPos: { top: 0, left: 0 } };
  },
  mounted() {
    renderLucideIcons(this.$el);
    this._closeMenu = (e) => {
      if (this.showMenu && !this.$el.contains(e.target)) {
        this.showMenu = false;
      }
    };
    document.addEventListener('click', this._closeMenu);
  },
  updated() {
    renderLucideIcons(this.$el);
  },
  beforeUnmount() {
    document.removeEventListener('click', this._closeMenu);
  },
  computed: {
    passDir() {
      const d = this.worker.disposition || '';
      return d.startsWith('pass:') ? d.slice(5) : null;
    },
    workerState() { return this.worker.state || 'idle'; },
    isWorking() { return this.workerState === 'working'; },
    canStart() {
      return this.workerState === 'idle';
    },
    isScheduled() {
      return this.worker.activation === 'at_time' || this.worker.activation === 'on_interval';
    },
    isPaused() {
      return this.worker.paused === true;
    },
    canMove() {
      return this.workerState === 'idle';
    },
    agentColor() {
      return agentColor(this.worker.agent);
    },
    workerIcon() {
      return getWorkerTypeIcon(this.worker);
    },
    expertiseTooltip() {
      return (this.worker.expertise_prompt || '').trim();
    },
    queuedTasks() {
      if (!this.worker.task_queue || !this.tasks) return [];
      return this.worker.task_queue.map(id => {
        const t = this.tasks.find(task => task.id === id);
        return t || { id, title: id };
      });
    },
    menuStyle() {
      return { top: this.menuPos.top + 'px', left: this.menuPos.left + 'px' };
    },
    lastOutput() {
      // Prefer live output buffer when working
      if (this.isWorking && this.outputLines?.length) {
        return this.outputLines.slice(-3).join('\n');
      }
      if (!this.worker.task_queue?.length || !this.tasks) return '';
      const task = this.tasks.find(t => t.id === this.worker.task_queue[0]);
      if (!task?.body) return '';
      const marker = '## Agent Output';
      const idx = task.body.indexOf(marker);
      if (idx < 0) return '';
      const output = task.body.substring(idx + marker.length).trim();
      const lines = output.split('\\n');
      return lines.slice(-3).join('\\n');
    }
  },
  methods: {
    onBodyClick() {
      if (this.isWorking) {
        this.$emit('open-focus', this.slotIndex);
      }
    },
    onBodyDblClick() {
      const taskId = this.queuedTasks.length ? this.queuedTasks[0].id : null;
      if (taskId) this.$emit('select-task', taskId);
    },
    onDragStart(e) {
      e.dataTransfer.setData('application/x-worker-slot', String(this.slotIndex));
      e.dataTransfer.effectAllowed = 'move';
    },
    onDragOver(e) {
      if (
        e.dataTransfer.types.includes(window.BULLPEN_TASK_DND_MIME) ||
        e.dataTransfer.types.includes('text/plain') ||
        e.dataTransfer.types.includes('application/x-worker-slot')
      ) {
        e.dataTransfer.dropEffect = 'move';
        this.dragOver = true;
      }
    },
    onDragLeave() { this.dragOver = false; },
    onDrop(e) {
      e.preventDefault();
      this.dragOver = false;
      const fromSlot = e.dataTransfer.getData('application/x-worker-slot');
      if (fromSlot !== '' && Number(fromSlot) !== this.slotIndex) {
        this.$root.moveWorker(Number(fromSlot), this.slotIndex);
        return;
      }
      const taskId = e.dataTransfer.getData(window.BULLPEN_TASK_DND_MIME) || e.dataTransfer.getData('text/plain');
      if (taskId) {
        this.$root.assignTask(taskId, this.slotIndex);
      }
    },
    toggleMenu() {
      if (this.showMenu) {
        this.showMenu = false;
        return;
      }
      const btn = this.$refs.menuBtn;
      if (btn) {
        const rect = btn.getBoundingClientRect();
        const menuWidth = 130;
        let left = rect.right - menuWidth;
        if (left < 4) left = rect.left;
        this.menuPos = { top: rect.bottom + 4, left };
      }
      this.showMenu = true;
    },
    menuEdit() {
      this.showMenu = false;
      this.$emit('configure', this.slotIndex);
    },
    menuRun() {
      this.showMenu = false;
      this.$root.startWorkerSlot(this.slotIndex);
    },
    menuStop() {
      this.showMenu = false;
      this.$root.stopWorkerSlot(this.slotIndex);
    },
    menuPause() {
      this.showMenu = false;
      this.$root.saveWorkerConfig({ slot: this.slotIndex, fields: { paused: true } });
    },
    menuUnpause() {
      this.showMenu = false;
      this.$root.saveWorkerConfig({ slot: this.slotIndex, fields: { paused: false } });
    },
    menuDuplicate() {
      this.showMenu = false;
      this.$root.duplicateWorker(this.slotIndex);
    },
    menuWatch() {
      this.showMenu = false;
      this.$emit('open-focus', this.slotIndex);
    },
    menuCopyTo() {
      this.showMenu = false;
      this.$emit('transfer', { slot: this.slotIndex, mode: 'copy' });
    },
    menuMoveTo() {
      this.showMenu = false;
      this.$emit('transfer', { slot: this.slotIndex, mode: 'move' });
    },
    menuDelete() {
      this.showMenu = false;
      this.$root.removeWorker(this.slotIndex);
    }
  }
};
