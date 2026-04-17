const WorkerCard = {
  props: ['worker', 'slotIndex', 'tasks', 'outputLines', 'multipleWorkspaces', 'neighborSlots', 'layoutMode', 'buildWorkerDragPayload', 'buildWorkerDragImage', 'canDropWorkerAtSlot', 'dropWorkerOnSlot'],
  emits: ['configure', 'select-task', 'open-focus', 'transfer', 'copy-worker'],
  template: `
    <div class="worker-card" :class="{ 'drag-over': dragOver, 'connect-target': connectTarget, 'worker-card--small': layoutMode === 'small' }"
         :style="layoutMode === 'small' ? { background: agentColor } : null"
         draggable="true"
         @dragstart="onDragStart"
         @dragend="onDragEnd"
         @dragover="onDragOver"
         @dragleave="onDragLeave"
         @drop.prevent="onDrop"
         @mousemove="onCardMouseMove"
         @mouseleave="onCardMouseLeave"
>
      <template v-for="dir in ['up','down','left','right']" :key="'handle-' + dir">
        <div v-if="canConnect(dir)"
             class="connect-handle"
             :class="['connect-handle-' + dir, { 'connect-handle-active': hoveredHandle === dir }]"
             draggable="true"
             @dragstart.stop="onHandleDragStart(dir, $event)"
             @dragend.stop="onHandleDragEnd"
             :title="'Drag to pass output ' + dir"></div>
      </template>
      <span v-if="passDir === 'up'" class="pass-indicator pass-up" :class="{ 'pass-connected': passConnectsToNeighbor }" title="This worker passes tickets up" aria-label="This worker passes tickets up">&#x25B2;</span>
      <span v-if="passDir === 'down'" class="pass-indicator pass-down" :class="{ 'pass-connected': passConnectsToNeighbor }" title="This worker passes tickets down" aria-label="This worker passes tickets down">&#x25BC;</span>
      <span v-if="passDir === 'left'" class="pass-indicator pass-left" :class="{ 'pass-connected': passConnectsToNeighbor }" title="This worker passes tickets left" aria-label="This worker passes tickets left">&#x25C0;</span>
      <span v-if="passDir === 'right'" class="pass-indicator pass-right" :class="{ 'pass-connected': passConnectsToNeighbor }" title="This worker passes tickets right" aria-label="This worker passes tickets right">&#x25B6;</span>
      <span v-if="passDir === 'random'" class="pass-indicator pass-random" title="This worker passes tickets in a random direction" aria-label="This worker passes tickets in a random direction">?</span>
      <div class="worker-card-header" :style="{ background: agentColor }" :title="expertiseTooltip || null" @dblclick="$emit('configure', slotIndex)">
        <div class="worker-card-identity">
          <i class="worker-type-icon worker-type-icon--card" :data-lucide="workerIcon" aria-hidden="true"></i>
          <span class="worker-card-name">{{ workerNameLabel }}</span>
        </div>
        <div class="worker-card-actions">
          <span class="worker-card-header-status">
            <span v-if="workerState !== 'idle' || isPaused" class="status-pill" :class="'status-' + workerState">
              {{ statusLabel }}
            </span>
            <span v-if="isWorking && currentTaskTokens !== null" class="worker-card-token-meta" title="Total tokens so far for current task">{{ formatTokens(currentTaskTokens) }}</span>
          </span>
          <button class="worker-menu-btn" ref="menuBtn" @click.stop="toggleMenu" title="Actions">&hellip;</button>
          <div v-if="showMenu" class="worker-menu" :style="menuStyle" @click.stop @keydown="onMenuKeydown">
            <button class="worker-menu-item" @click="menuEdit"><i class="menu-item-icon" data-lucide="pencil" aria-hidden="true"></i><span class="menu-item-label">Edit</span></button>
            <button v-if="canStart && !isPaused" class="worker-menu-item" @click="menuRun"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">Run</span></button>
            <button v-if="isWorking" class="worker-menu-item" @click="menuWatch"><i class="menu-item-icon" data-lucide="eye" aria-hidden="true"></i><span class="menu-item-label">Watch</span></button>
            <button v-if="isWorking" class="worker-menu-item" @click="menuStop"><i class="menu-item-icon" data-lucide="square" aria-hidden="true"></i><span class="menu-item-label">Stop</span></button>
            <button v-if="isScheduled && !isPaused" class="worker-menu-item" @click="menuPause"><i class="menu-item-icon" data-lucide="pause" aria-hidden="true"></i><span class="menu-item-label">Pause</span></button>
            <button v-if="isScheduled && isPaused" class="worker-menu-item" @click="menuUnpause"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">Unpause</span></button>
            <button class="worker-menu-item" @click="menuDuplicate"><i class="menu-item-icon" data-lucide="copy" aria-hidden="true"></i><span class="menu-item-label">Duplicate</span></button>
            <button class="worker-menu-item" @click="menuCopyWorker"><i class="menu-item-icon" data-lucide="clipboard" aria-hidden="true"></i><span class="menu-item-label">Copy Worker</span></button>
            <button v-if="multipleWorkspaces" class="worker-menu-item" @click="menuCopyTo"><i class="menu-item-icon" data-lucide="copy" aria-hidden="true"></i><span class="menu-item-label">Copy to workspace&hellip;</span></button>
            <button v-if="multipleWorkspaces && canMove" class="worker-menu-item" @click="menuMoveTo"><i class="menu-item-icon" data-lucide="arrow-right" aria-hidden="true"></i><span class="menu-item-label">Move to workspace&hellip;</span></button>
            <button class="worker-menu-item worker-menu-danger" @click="menuDelete"><i class="menu-item-icon" data-lucide="trash-2" aria-hidden="true"></i><span class="menu-item-label">Delete</span></button>
          </div>
        </div>
      </div>
      <div v-if="layoutMode !== 'small'" class="worker-card-body" @click.stop="onBodyClick" @dblclick.stop="onBodyDblClick">
        <div class="worker-card-queue" v-if="layoutMode !== 'small' && queuedTasks.length">
          <div v-for="t in queuedTasks" :key="t.id" class="worker-queue-item" :title="t.title"
               @click.stop="$emit('select-task', t.id)">
            <i class="ticket-type-icon ticket-type-icon--worker-queue" data-lucide="tag" aria-hidden="true"></i>
            <span class="worker-queue-title">{{ t.title }}</span>
          </div>
        </div>
        <div v-else class="worker-card-empty">No tasks queued</div>
        <div v-if="showOutputPane && isWorking && lastOutput" class="worker-card-output">
          <pre>{{ lastOutput }}</pre>
        </div>
      </div>
    </div>
  `,
  data() {
    return { dragOver: false, connectTarget: false, showMenu: false, menuPos: { top: 0, left: 0 }, elapsed: '0s', _timer: null, hoveredHandle: null };
  },
  mounted() {
    renderLucideIcons(this.$el);
    this._timer = setInterval(() => this.updateElapsed(), 1000);
    this.updateElapsed();
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
    if (this._timer) clearInterval(this._timer);
    document.removeEventListener('click', this._closeMenu);
    this.removeDragImage();
  },
  computed: {
    passDir() {
      const d = this.worker.disposition || '';
      return d.startsWith('pass:') ? d.slice(5) : null;
    },
    passConnectsToNeighbor() {
      return !!(this.passDir && this.neighborSlots && this.neighborSlots[this.passDir] != null);
    },
    workerState() { return this.worker.state || 'idle'; },
    isWorking() { return this.workerState === 'working'; },
    showOutputPane() {
      return this.layoutMode !== 'small';
    },
    statusLabel() {
      if (this.isPaused) return 'PAUSED';
      if (this.isWorking) return `BUSY ${this.elapsed}`;
      return this.workerState.toUpperCase();
    },
    taskQueueCount() {
      return Array.isArray(this.worker?.task_queue) ? this.worker.task_queue.length : 0;
    },
    workerNameLabel() {
      const name = this.worker?.name || '';
      return this.taskQueueCount > 0 ? `${name} (${this.taskQueueCount})` : name;
    },
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
    currentTask() {
      if (!this.worker.task_queue?.length || !this.tasks) return null;
      const currentTaskId = this.worker.task_queue[0];
      return this.tasks.find(t => t.id === currentTaskId) || null;
    },
    currentTaskTokens() {
      if (!this.currentTask) return null;
      const n = Number(this.currentTask.tokens);
      if (!Number.isFinite(n) || n < 0) return 0;
      return Math.floor(n);
    },
    menuStyle() {
      return { top: this.menuPos.top + 'px', left: this.menuPos.left + 'px' };
    },
    lastOutput() {
      // Prefer live output buffer when working
      if (this.isWorking && this.outputLines?.length) {
        return this.outputLines.slice(-5).join('\n');
      }
      if (!this.worker.task_queue?.length || !this.tasks) return '';
      const task = this.tasks.find(t => t.id === this.worker.task_queue[0]);
      if (!task?.body) return '';
      const marker = '## Agent Output';
      const idx = task.body.indexOf(marker);
      if (idx < 0) return '';
      const output = task.body.substring(idx + marker.length).trim();
      const lines = output.split('\\n');
      return lines.slice(-5).join('\\n');
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
    canConnect(dir) {
      return !!(this.neighborSlots && this.neighborSlots[dir] != null);
    },
    onCardMouseMove(e) {
      // Reveal at most one drag handle — whichever edge the cursor is closest
      // to, within a small threshold. This keeps the card body free of drag
      // affordances so ordinary clicks (e.g. to open the focus view) are
      // unobstructed, and guarantees we never show all four handles at once.
      const rect = this.$el.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const threshold = 24;
      const distances = { up: y, down: rect.height - y, left: x, right: rect.width - x };
      let nearest = null;
      let nearestDist = Infinity;
      for (const dir of ['up', 'down', 'left', 'right']) {
        if (!this.canConnect(dir)) continue;
        const d = distances[dir];
        if (d <= threshold && d < nearestDist) {
          nearest = dir;
          nearestDist = d;
        }
      }
      if (this.hoveredHandle !== nearest) this.hoveredHandle = nearest;
    },
    onCardMouseLeave() {
      this.hoveredHandle = null;
    },
    onDragStart(e) {
      const payload = typeof this.buildWorkerDragPayload === 'function'
        ? this.buildWorkerDragPayload(this.slotIndex)
        : { source: this.slotIndex, group: [this.slotIndex] };
      e.dataTransfer.setData('application/x-worker-slot', String(this.slotIndex));
      try {
        e.dataTransfer.setData('application/x-worker-group', JSON.stringify(payload));
      } catch (_err) { /* ignore */ }
      e.dataTransfer.effectAllowed = 'move';
      window._bullpenWorkerDrag = payload;
      this.removeDragImage();
      if (typeof this.buildWorkerDragImage === 'function') {
        const dragImage = this.buildWorkerDragImage(this.slotIndex, {
          clientX: e.clientX,
          clientY: e.clientY,
        });
        if (dragImage?.element && typeof e.dataTransfer.setDragImage === 'function') {
          const offsetX = Number.isFinite(Number(dragImage.offsetX)) ? Number(dragImage.offsetX) : 0;
          const offsetY = Number.isFinite(Number(dragImage.offsetY)) ? Number(dragImage.offsetY) : 0;
          e.dataTransfer.setDragImage(dragImage.element, offsetX, offsetY);
          this._dragImageEl = dragImage.element;
        }
      }
    },
    onDragEnd() {
      window._bullpenWorkerDrag = null;
      this.removeDragImage();
    },
    onHandleDragStart(dir, e) {
      if (!this.canConnect(dir)) {
        e.preventDefault();
        return;
      }
      const payload = { source: this.slotIndex, direction: dir, target: this.neighborSlots[dir] };
      // Custom MIME type stores the full payload; a global mirror lets dragover
      // handlers know the intended target without having to read dataTransfer
      // (which is restricted to drop events in most browsers).
      try {
        e.dataTransfer.setData('application/x-worker-connect', JSON.stringify(payload));
      } catch (_err) { /* ignore */ }
      e.dataTransfer.effectAllowed = 'link';
      window._bullpenConnectDrag = payload;
    },
    onHandleDragEnd() {
      window._bullpenConnectDrag = null;
    },
    onDragOver(e) {
      const types = e.dataTransfer.types;
      if (types.includes('application/x-worker-connect')) {
        const drag = window._bullpenConnectDrag;
        if (drag && drag.target === this.slotIndex) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'link';
          this.connectTarget = true;
        } else {
          // Do not call preventDefault — cursor shows "no drop" on non-targets.
          e.dataTransfer.dropEffect = 'none';
        }
        return;
      }
      if (
        types.includes(window.BULLPEN_TASK_DND_MIME) ||
        types.includes('text/plain') ||
        types.includes('application/x-worker-slot') ||
        types.includes('application/x-worker-group')
      ) {
        if (types.includes('application/x-worker-slot') || types.includes('application/x-worker-group')) {
          const drag = window._bullpenWorkerDrag;
          const source = Number(drag?.source);
          const canDrop = Number.isInteger(source)
            ? (typeof this.canDropWorkerAtSlot === 'function' ? !!this.canDropWorkerAtSlot(source, this.slotIndex) : true)
            : false;
          if (canDrop) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            this.dragOver = true;
          } else {
            e.dataTransfer.dropEffect = 'none';
            this.dragOver = false;
          }
          return;
        }
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        this.dragOver = true;
      }
    },
    onDragLeave() { this.dragOver = false; this.connectTarget = false; },
    onDrop(e) {
      e.preventDefault();
      this.dragOver = false;
      this.connectTarget = false;
      const connectData = e.dataTransfer.getData('application/x-worker-connect');
      if (connectData) {
        e.stopPropagation();
        try {
          const payload = JSON.parse(connectData);
          if (payload && payload.target === this.slotIndex) {
            this.$root.saveWorkerConfig({ slot: payload.source, fields: { disposition: 'pass:' + payload.direction } });
          }
        } catch (_err) { /* ignore malformed payload */ }
        window._bullpenConnectDrag = null;
        return;
      }
      const fromSlot = e.dataTransfer.getData('application/x-worker-slot');
      const dragSource = fromSlot !== '' ? Number(fromSlot) : Number(window._bullpenWorkerDrag?.source);
      if (Number.isInteger(dragSource)) {
        e.stopPropagation();
        if (typeof this.dropWorkerOnSlot === 'function') {
          this.dropWorkerOnSlot(dragSource, this.slotIndex);
        } else if (dragSource !== this.slotIndex) {
          this.$root.moveWorker(dragSource, this.slotIndex);
        }
        return;
      }
      const taskId = e.dataTransfer.getData(window.BULLPEN_TASK_DND_MIME) || e.dataTransfer.getData('text/plain');
      if (taskId) {
        e.stopPropagation();
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
    openMenuAndFocus() {
      if (!this.showMenu) this.toggleMenu();
      this.$nextTick(() => {
        const first = this.$el.querySelector('.worker-menu .worker-menu-item:not([disabled])');
        if (first) first.focus();
      });
    },
    onMenuKeydown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        this.showMenu = false;
        const viewport = document.querySelector('.worker-grid-viewport');
        if (viewport) viewport.focus();
        return;
      }
      const items = Array.from(this.$el.querySelectorAll('.worker-menu .worker-menu-item:not([disabled])'));
      if (!items.length) return;
      const currentIdx = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        items[(currentIdx + 1) % items.length].focus();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        items[currentIdx <= 0 ? items.length - 1 : currentIdx - 1].focus();
      } else if (e.key === 'Home') {
        e.preventDefault();
        e.stopPropagation();
        items[0].focus();
      } else if (e.key === 'End') {
        e.preventDefault();
        e.stopPropagation();
        items[items.length - 1].focus();
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.stopPropagation();
      }
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
    menuCopyWorker() {
      this.showMenu = false;
      this.$emit('copy-worker', this.slotIndex);
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
    },
    removeDragImage() {
      if (this._dragImageEl && this._dragImageEl.parentNode) {
        this._dragImageEl.parentNode.removeChild(this._dragImageEl);
      }
      this._dragImageEl = null;
    },
    updateElapsed() {
      if (!this.isWorking || !this.worker?.started_at) {
        this.elapsed = '0s';
        return;
      }
      const start = new Date(this.worker.started_at).getTime();
      const now = Date.now();
      const secs = Math.floor((now - start) / 1000);
      if (secs < 0 || Number.isNaN(secs)) {
        this.elapsed = '0s';
        return;
      }
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      const s = secs % 60;
      if (h > 0) {
        this.elapsed = `${h}h ${m}m ${s}s`;
        return;
      }
      this.elapsed = m > 0 ? `${m}m ${s}s` : `${s}s`;
    },
    formatTokens(n) {
      if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M tok';
      if (n >= 1000) return (n / 1000).toFixed(1) + 'k tok';
      return String(n) + ' tok';
    }
  }
};
