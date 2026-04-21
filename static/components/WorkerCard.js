const WorkerCard = {
  props: ['worker', 'slotIndex', 'tasks', 'outputLines', 'multipleWorkspaces', 'neighborSlots', 'layoutMode', 'buildWorkerDragPayload', 'buildWorkerDragImage', 'canDropWorkerAtSlot', 'dropWorkerOnSlot', 'updateSingletonWorkerDrag', 'endSingletonWorkerDrag', 'cancelSingletonWorkerDrag'],
  emits: ['configure', 'select-task', 'open-focus', 'transfer', 'copy-worker', 'menu-closed'],
  template: `
    <div class="worker-card" :class="{ 'drag-over': dragOver, 'connect-target': connectTarget, 'worker-card--small': layoutMode === 'small', 'is-dragging': isDragging, 'worker-card--disabled-type': isDisabledType }"
         :style="layoutMode === 'small' ? { background: agentColor } : null"
         draggable="true"
         @pointerdown="onPointerDown"
         @pointermove="onPointerMove"
         @pointerup="onPointerUp"
         @pointercancel="onPointerCancel"
         @lostpointercapture="onPointerLostCapture"
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
      <div class="worker-card-header" :style="{ background: agentColor }" @dblclick="$emit('configure', slotIndex)">
        <div class="worker-card-identity">
          <div class="worker-card-title-row">
            <i class="worker-type-icon worker-type-icon--card" :data-lucide="workerIcon" aria-hidden="true"></i>
            <span class="worker-card-name">{{ workerNameLabel }}</span>
          </div>
          <div v-if="serviceModeBadge || servicePortLabel" class="worker-card-service-meta">
            <span v-if="serviceModeBadge" class="worker-type-badge">{{ serviceModeBadge }}</span>
            <span v-if="servicePortLabel" class="worker-type-badge">{{ servicePortLabel }}</span>
          </div>
        </div>
        <div class="worker-card-actions">
          <span class="worker-card-header-status">
            <span v-if="(workerState !== 'idle' || isPaused) && !pillInBody" class="status-pill" :class="['status-' + workerState, { 'status-pill-clickable': isWorking || isService }]" @click.stop="onStatusPillClick">
              {{ statusLabel }}
            </span>
          </span>
          <button class="worker-menu-btn" ref="menuBtn" @click.stop="toggleMenu" title="Actions">&hellip;</button>
          <div v-if="showMenu" class="worker-menu" :style="menuStyle" @click.stop @keydown="onMenuKeydown">
            <button v-if="canConfigure" class="worker-menu-item" @click="menuEdit"><i class="menu-item-icon" data-lucide="pencil" aria-hidden="true"></i><span class="menu-item-label">Edit</span></button>
            <button v-if="canStart && !isPaused" class="worker-menu-item" @click="menuRun"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">{{ isService ? 'Start' : 'Run' }}</span></button>
            <button v-if="canRestart" class="worker-menu-item" @click="menuRestart"><i class="menu-item-icon" data-lucide="rotate-cw" aria-hidden="true"></i><span class="menu-item-label">Restart</span></button>
            <button v-if="canWatch" class="worker-menu-item" @click="menuWatch"><i class="menu-item-icon" data-lucide="eye" aria-hidden="true"></i><span class="menu-item-label">Watch</span></button>
            <button v-if="canStop" class="worker-menu-item" @click="menuStop"><i class="menu-item-icon" data-lucide="square" aria-hidden="true"></i><span class="menu-item-label">Stop</span></button>
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
        <div v-if="isDisabledType" class="worker-card-disabled-badge" :title="disabledTypeMessage">
          {{ disabledTypeMessage }}
        </div>
        <div class="worker-card-queue" v-if="layoutMode !== 'small' && queuedTasks.length">
          <div v-for="t in queuedTasks" :key="t.id" class="worker-queue-item" :title="t.title"
               @click.stop="$emit('select-task', t.id)">
            <i class="ticket-type-icon ticket-type-icon--worker-queue" data-lucide="tag" aria-hidden="true"></i>
            <span class="worker-queue-title">{{ t.title }}</span>
          </div>
        </div>
        <div v-else class="worker-card-empty">
          <span v-if="pillInBody" class="status-pill" :class="['status-' + workerState, { 'status-pill-clickable': isWorking || isService }]" @click.stop="onStatusPillClick">
            {{ statusLabel }}
          </span>
          <template v-else>{{ emptyLabel }}</template>
        </div>
        <div v-if="showOutputPane && (isWorking || isService) && lastOutput" class="worker-card-output">
          <pre>{{ lastOutput }}</pre>
        </div>
      </div>
    </div>
  `,
  data() {
    return {
      dragOver: false,
      connectTarget: false,
      showMenu: false,
      menuPos: { top: 0, left: 0 },
      elapsed: '0s',
      _timer: null,
      hoveredHandle: null,
      shiftDragIntent: false,
      isDragging: false,
      pointerWorkerDrag: null,
    };
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
    document.body.classList.remove('worker-singleton-dragging');
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
    workerState() { return this.worker.service_state?.state || this.worker.state || 'idle'; },
    isWorking() { return ['working', 'starting', 'running', 'healthy', 'unhealthy'].includes(this.workerState); },
    showOutputPane() {
      return this.layoutMode !== 'small';
    },
    pillInBody() {
      return this.layoutMode !== 'small' && this.isService && (this.workerState !== 'idle' || this.isPaused);
    },
    statusLabel() {
      if (this.isPaused) return 'PAUSED';
      if (this.isService && this.workerState === 'running') return `RUNNING ${this.elapsed}`;
      if (this.isService && this.workerState === 'starting') return `STARTING ${this.elapsed}`;
      if (this.isService && this.workerState === 'healthy') return `HEALTHY ${this.elapsed}`;
      if (this.isService && this.workerState === 'unhealthy') return `UNHEALTHY ${this.elapsed}`;
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
    serviceModeBadge() {
      if (!this.isService) return '';
      if (this.worker.command_source === 'procfile') {
        return `Procfile:${this.worker.procfile_process || 'web'}`;
      }
      return '';
    },
    servicePortLabel() {
      if (!this.isService) return '';
      const port = this.worker.port;
      return port ? `:${port}` : '';
    },
    canStart() {
      if (this.isService) return ['idle', 'stopped', 'crashed'].includes(this.workerState);
      return this.workerState === 'idle' && !this.isDisabledType;
    },
    canStop() {
      if (this.isService) return ['starting', 'running', 'healthy', 'unhealthy'].includes(this.workerState);
      return this.isWorking;
    },
    canRestart() {
      return this.isService && ['idle', 'stopped', 'running', 'healthy', 'unhealthy', 'crashed'].includes(this.workerState);
    },
    canWatch() {
      return this.isService || this.isWorking;
    },
    canConfigure() {
      return !this.isUnknownType;
    },
    isScheduled() {
      return this.worker.activation === 'at_time' || this.worker.activation === 'on_interval';
    },
    isPaused() {
      return this.worker.paused === true;
    },
    canMove() {
      return this.workerState === 'idle' || (this.isService && ['stopped', 'crashed'].includes(this.workerState));
    },
    agentColor() {
      return workerColor(this.worker);
    },
    workerIcon() {
      return getWorkerTypeIcon(this.worker);
    },
    workerTypeLabel() {
      return workerTypeLabel(this.worker);
    },
    isShell() {
      return isShellWorker(this.worker);
    },
    isService() {
      return isServiceWorker(this.worker);
    },
    isEval() {
      return isEvalWorker(this.worker);
    },
    isUnknownType() {
      return isUnknownWorkerType(this.worker);
    },
    isDisabledType() {
      return this.isEval || this.isUnknownType;
    },
    disabledTypeMessage() {
      if (this.isUnknownType) return 'Worker type not installed';
      if (this.isEval) return 'Eval workers reserved for a future release';
      return '';
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
      if ((this.isWorking || this.isService) && this.outputLines?.length) {
        return this.outputLines.slice(-5).join('\n');
      }
      if (!this.worker.task_queue?.length || !this.tasks) return '';
      const task = this.tasks.find(t => t.id === this.worker.task_queue[0]);
      if (!task?.body) return '';
      let idx = -1;
      let markerLen = 0;
      for (const marker of ['## Agent Output', '## Worker Output']) {
        const i = task.body.indexOf(marker);
        if (i < 0) continue;
        if (idx < 0 || i < idx) { idx = i; markerLen = marker.length; }
      }
      if (idx < 0) return '';
      const output = task.body.substring(idx + markerLen).trim();
      const lines = output.split('\n');
      return lines.slice(-5).join('\n');
    },
    emptyLabel() {
      if (this.isService) return this.workerState === 'idle' ? 'Stopped' : this.workerState;
      return 'Idle';
    }
  },
  methods: {
    onBodyClick() {
      if (this.isWorking || this.isService) {
        this.$emit('open-focus', this.slotIndex);
      }
    },
    onStatusPillClick() {
      if (this.isWorking || this.isService) {
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
    onPointerDown(e) {
      if (e.button !== 0) return;
      if (e.target.closest('.connect-handle, .status-pill, .worker-menu-btn, .worker-menu, button, input, select, textarea')) return;
      this.shiftDragIntent = !!e.shiftKey;
      if (!e.shiftKey || typeof this.buildWorkerDragPayload !== 'function') return;
      const payload = this.buildWorkerDragPayload(this.slotIndex, {
        singleton: true,
        clientX: e.clientX,
        clientY: e.clientY,
      });
      this.pointerWorkerDrag = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        payload,
        active: false,
      };
      window._bullpenWorkerDrag = payload;
      this.isDragging = true;
      document.body.classList.add('worker-singleton-dragging');
      this.$el.setPointerCapture?.(e.pointerId);
      e.preventDefault();
      e.stopPropagation();
    },
    onPointerMove(e) {
      const drag = this.pointerWorkerDrag;
      if (!drag || drag.pointerId !== e.pointerId) return;
      e.preventDefault();
      e.stopPropagation();
      if (!drag.active && Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) <= 5) return;
      drag.active = true;
      window._bullpenWorkerDrag = drag.payload;
      if (typeof this.updateSingletonWorkerDrag === 'function') {
        this.updateSingletonWorkerDrag(drag.payload.source, e);
      }
    },
    onPointerUp(e) {
      const drag = this.pointerWorkerDrag;
      if (drag) {
        if (drag.active && typeof this.endSingletonWorkerDrag === 'function') {
          this.endSingletonWorkerDrag(drag.payload.source, e);
          window._bullpenSuppressWorkerClickUntil = Date.now() + 250;
        } else if (typeof this.cancelSingletonWorkerDrag === 'function') {
          this.cancelSingletonWorkerDrag();
        }
        this.pointerWorkerDrag = null;
        this.$el.releasePointerCapture?.(drag.pointerId);
        e.preventDefault();
        e.stopPropagation();
      }
      this.shiftDragIntent = false;
      this.isDragging = false;
      if (window._bullpenWorkerDrag?.source === drag?.payload?.source) window._bullpenWorkerDrag = null;
      document.body.classList.remove('worker-singleton-dragging');
    },
    onPointerCancel(e) {
      const drag = this.pointerWorkerDrag;
      if (drag) {
        if (typeof this.cancelSingletonWorkerDrag === 'function') this.cancelSingletonWorkerDrag();
        this.pointerWorkerDrag = null;
        this.$el.releasePointerCapture?.(drag.pointerId);
      }
      this.shiftDragIntent = false;
      this.isDragging = false;
      if (window._bullpenWorkerDrag?.source === drag?.payload?.source) window._bullpenWorkerDrag = null;
      document.body.classList.remove('worker-singleton-dragging');
    },
    onPointerLostCapture(e) {
      if (this.pointerWorkerDrag && this.pointerWorkerDrag.pointerId === e.pointerId) {
        this.onPointerCancel(e);
      }
    },
    onDragStart(e) {
      if (this.pointerWorkerDrag) {
        e.preventDefault();
        return;
      }
      const singleton = !!(e.shiftKey || this.shiftDragIntent);
      const payload = typeof this.buildWorkerDragPayload === 'function'
        ? this.buildWorkerDragPayload(this.slotIndex, {
          singleton,
          clientX: e.clientX,
          clientY: e.clientY,
        })
        : { source: this.slotIndex, group: [this.slotIndex] };
      e.dataTransfer.setData('application/x-worker-slot', String(this.slotIndex));
      try {
        e.dataTransfer.setData('application/x-worker-group', JSON.stringify(payload));
      } catch (_err) { /* ignore */ }
      e.dataTransfer.effectAllowed = 'move';
      window._bullpenWorkerDrag = payload;
      this.isDragging = true;
      this.removeDragImage();
      if (typeof this.buildWorkerDragImage === 'function') {
        const dragImage = this.buildWorkerDragImage(this.slotIndex, {
          clientX: e.clientX,
          clientY: e.clientY,
        }, { singleton });
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
      this.shiftDragIntent = false;
      this.isDragging = false;
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
        types.includes('application/x-worker-group') ||
        window._bullpenWorkerDrag
      ) {
        if (types.includes('application/x-worker-slot') || types.includes('application/x-worker-group') || window._bullpenWorkerDrag) {
          const drag = window._bullpenWorkerDrag;
          const source = Number(drag?.source);
          const canDrop = Number.isInteger(source)
            ? (typeof this.canDropWorkerAtSlot === 'function' ? !!this.canDropWorkerAtSlot(source, this.slotIndex, e) : true)
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
        if (typeof this.dropWorkerOnSlot === 'function') {
          const handled = this.dropWorkerOnSlot(dragSource, this.slotIndex, e);
          if (handled) {
            e.stopPropagation();
          }
        } else if (dragSource !== this.slotIndex) {
          e.stopPropagation();
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
      this.$emit('menu-opened');
      this.$nextTick(() => {
        const first = this.$el.querySelector('.worker-menu .worker-menu-item:not([disabled])');
        if (first) first.focus();
      });
    },
    openMenuAndFocus() {
      if (!this.showMenu) this.toggleMenu();
    },
    closeMenuAndRestoreFocus() {
      this.showMenu = false;
      this.$emit('menu-closed');
    },
    onMenuKeydown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        this.closeMenuAndRestoreFocus();
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
      this.closeMenuAndRestoreFocus();
      this.$emit('configure', this.slotIndex);
    },
    menuRun() {
      this.closeMenuAndRestoreFocus();
      this.$root.startWorkerSlot(this.slotIndex);
    },
    menuStop() {
      this.closeMenuAndRestoreFocus();
      this.$root.stopWorkerSlot(this.slotIndex);
    },
    menuRestart() {
      this.closeMenuAndRestoreFocus();
      this.$root.restartServiceSlot(this.slotIndex);
    },
    menuPause() {
      this.closeMenuAndRestoreFocus();
      this.$root.saveWorkerConfig({ slot: this.slotIndex, fields: { paused: true } });
    },
    menuUnpause() {
      this.closeMenuAndRestoreFocus();
      this.$root.saveWorkerConfig({ slot: this.slotIndex, fields: { paused: false } });
    },
    menuDuplicate() {
      this.closeMenuAndRestoreFocus();
      this.$root.duplicateWorker(this.slotIndex);
    },
    menuCopyWorker() {
      this.closeMenuAndRestoreFocus();
      this.$emit('copy-worker', this.slotIndex);
    },
    menuWatch() {
      this.closeMenuAndRestoreFocus();
      this.$emit('open-focus', this.slotIndex);
    },
    menuCopyTo() {
      this.closeMenuAndRestoreFocus();
      this.$emit('transfer', { slot: this.slotIndex, mode: 'copy' });
    },
    menuMoveTo() {
      this.closeMenuAndRestoreFocus();
      this.$emit('transfer', { slot: this.slotIndex, mode: 'move' });
    },
    menuDelete() {
      this.closeMenuAndRestoreFocus();
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
  }
};
