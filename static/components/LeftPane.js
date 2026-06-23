const LeftPane = {
  props: ['tasks', 'layout', 'visible', 'config', 'projects', 'projectsLoaded', 'projectsRoot', 'activeWorkspaceId', 'workspaces', 'multipleWorkspaces'],
  emits: ['new-task', 'select-task', 'switch-workspace', 'add-project', 'new-project', 'clone-project', 'remove-project', 'configure-worker', 'open-focus', 'transfer-worker', 'copy-worker', 'move-task-project'],
  template: `
    <div class="left-pane" :class="{ collapsed: !visible, resizing: !!resizing }" :style="leftPaneStyle">
      <div
        v-if="visible"
        class="left-pane-resize"
        @pointerdown="onResizeDown"
        @dblclick="resetWidth"
        title="Drag to resize"
      ></div>
      <div class="left-pane-scroll">
      <div v-if="projects" class="left-pane-section" :class="{ 'project-add-only': projects.length === 0 }">
        <div class="section-header">
          <h3>Projects</h3>
          <div class="project-menu-wrap" @click.stop>
            <button class="btn btn-sm" @click="toggleProjectMenu">...</button>
            <div v-if="showEmptyProjectHint" class="project-menu-tooltip" role="status" aria-live="polite">
              <span>Add a project from /workspace to start.</span>
              <button class="btn-icon project-hint-dismiss" title="Dismiss" @click.stop="dismissEmptyProjectHint">&times;</button>
            </div>
            <div v-if="showProjectMenu" class="project-menu">
              <button class="project-menu-item" @click="promptAddProject"><i class="menu-item-icon" data-lucide="folder-open" aria-hidden="true"></i><span class="menu-item-label">Add Project</span></button>
              <button class="project-menu-item" @click="promptNewProject"><i class="menu-item-icon" data-lucide="folder-plus" aria-hidden="true"></i><span class="menu-item-label">New Project</span></button>
              <button class="project-menu-item" @click="promptCloneProject"><i class="menu-item-icon" data-lucide="git-branch-plus" aria-hidden="true"></i><span class="menu-item-label">Clone from Git</span></button>
            </div>
          </div>
        </div>
        <div v-if="projects.length > 0" class="project-list">
          <div v-for="p in projects" :key="p.id"
               class="project-item"
               :class="{ active: p.id === activeWorkspaceId, unavailable: p.available === false, 'drag-over': projectDragOverId === p.id }"
               @dragover.prevent="onProjectDragOver($event, p)"
               @dragleave="onProjectDragLeave($event, p)"
               @drop.prevent="onProjectDrop($event, p)"
               @click="p.available !== false && $emit('switch-workspace', p.id)"
               :title="p.available === false ? 'Directory not found: ' + p.path : ''">
            <span class="project-name">
              <i class="project-label-icon" :data-lucide="p.available === false ? 'folder-x' : 'folder'" aria-hidden="true"></i>
              <span class="project-label-text">{{ p.name }}</span>
            </span>
            <span class="project-item-actions">
              <span v-if="p.available !== false && unseenCount(p.id)" class="project-badge">{{ unseenCount(p.id) }}</span>
              <button
                v-if="canRemoveProject(p)"
                class="btn-icon project-remove-btn"
                :class="{ 'project-remove-btn--visible': p.available === false }"
                title="Remove project"
                @click.stop="confirmRemoveProject(p)"
              >&times;</button>
            </span>
          </div>
        </div>
      </div>
      <div v-if="activeWorkspaceId" class="left-pane-section">
        <div class="section-header">
          <select class="column-select" v-model="selectedColumn">
            <option v-for="col in columns" :key="col.key" :value="col.key">{{ col.label }}</option>
          </select>
          <button class="btn btn-sm" @click="$emit('new-task')">+ New Ticket</button>
        </div>
        <div class="inbox-list">
          <div v-if="filteredTasks.length === 0" class="empty-state">No tickets in {{ selectedColumnLabel }}</div>
          <div v-for="task in filteredTasks" :key="task.id"
               class="inbox-item"
               draggable="true"
               @dragstart="onDragStart($event, task.id)"
               @dragend="onDragEnd"
               @click="$emit('select-task', task.id)">
            <span class="inbox-title-wrap">
              <i class="ticket-type-icon ticket-type-icon--inbox" data-lucide="tag" aria-hidden="true"></i>
              <span class="inbox-title">{{ task.title }}</span>
            </span>
            <span class="badge" :class="'priority-' + (task.priority || 'normal')">{{ task.priority || 'normal' }}</span>
          </div>
        </div>
      </div>
      <div v-if="activeWorkspaceId" class="left-pane-section">
        <div class="section-header">
          <h3>Workers</h3>
        </div>
        <div class="worker-roster">
          <div v-if="!workerList.length" class="empty-state">No workers configured</div>
          <div v-for="w in workerList" :key="w.slot"
               class="roster-item"
               :class="{ 'drag-over': rosterDragSlot === w.slot }"
               :style="{ background: workerColor(w) }"
               @dragover.prevent="onRosterDragOver($event, w)"
               @dragleave="onRosterDragLeave"
               @drop="onRosterDrop($event, w.slot)">
            <span class="roster-name">
              <i class="worker-type-icon worker-type-icon--roster" :data-lucide="workerTypeIcon(w)" aria-hidden="true"></i>
              <span class="roster-label">{{ w.name }}</span>
            </span>
            <span class="status-pill" :class="'status-' + workerStatusClass(w)">{{ workerStatusLabel(w) }}</span>
            <button class="roster-worker-menu-btn" @click.stop="toggleWorkerMenu(w, $event)" title="Actions" aria-label="Worker actions">&hellip;</button>
            <Teleport to="body">
              <div v-if="openRosterWorkerMenuSlot === w.slot" ref="rosterWorkerMenu" class="worker-menu" :style="rosterWorkerMenuStyle" @click.stop @keydown="onWorkerMenuKeydown">
                <div class="worker-menu-section-label">This Worker</div>
                <button v-if="canConfigureWorker(w)" class="worker-menu-item" @click="rosterMenuEdit(w.slot)"><i class="menu-item-icon" data-lucide="pencil" aria-hidden="true"></i><span class="menu-item-label">Edit</span></button>
                <button v-if="canStartWorker(w) && !isPausedWorker(w)" class="worker-menu-item" @click="rosterMenuRun(w.slot)"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">{{ runMenuLabel(w) }}</span></button>
                <button v-if="canRestartWorker(w)" class="worker-menu-item" @click="rosterMenuRestart(w.slot)"><i class="menu-item-icon" data-lucide="rotate-cw" aria-hidden="true"></i><span class="menu-item-label">Restart</span></button>
                <button v-if="canWatchWorker(w)" class="worker-menu-item" @click="rosterMenuWatch(w.slot)"><i class="menu-item-icon" data-lucide="eye" aria-hidden="true"></i><span class="menu-item-label">Watch</span></button>
                <button v-if="isServiceWorkerType(w)" class="worker-menu-item" :disabled="!serviceSiteUrl(w)" @click="rosterMenuOpenSite(w.slot)"><i class="menu-item-icon" data-lucide="external-link" aria-hidden="true"></i><span class="menu-item-label">Open site in browser</span></button>
                <button v-if="canStopWorker(w)" class="worker-menu-item" @click="rosterMenuStop(w.slot)"><i class="menu-item-icon" data-lucide="square" aria-hidden="true"></i><span class="menu-item-label">Stop</span></button>
                <button v-if="canPauseWorker(w) && !isPausedWorker(w)" class="worker-menu-item" @click="rosterMenuPause(w.slot)"><i class="menu-item-icon" data-lucide="pause" aria-hidden="true"></i><span class="menu-item-label">Pause Worker</span></button>
                <button v-if="canPauseWorker(w) && isPausedWorker(w)" class="worker-menu-item" @click="rosterMenuUnpause(w.slot)"><i class="menu-item-icon" data-lucide="play" aria-hidden="true"></i><span class="menu-item-label">Unpause Worker</span></button>
                <button class="worker-menu-item" @click="rosterMenuDuplicate(w.slot)"><i class="menu-item-icon" data-lucide="copy" aria-hidden="true"></i><span class="menu-item-label">Duplicate</span></button>
                <button class="worker-menu-item" @click="rosterMenuCopyWorker(w.slot)"><i class="menu-item-icon" data-lucide="clipboard" aria-hidden="true"></i><span class="menu-item-label">Copy Worker</span></button>
                <button class="worker-menu-item" @click="rosterMenuExportWorker(w.slot)"><i class="menu-item-icon" data-lucide="download" aria-hidden="true"></i><span class="menu-item-label">Export Worker</span></button>
                <button v-if="multipleWorkspaces" class="worker-menu-item" @click="rosterMenuCopyTo(w.slot)"><i class="menu-item-icon" data-lucide="copy" aria-hidden="true"></i><span class="menu-item-label">Copy to workspace&hellip;</span></button>
                <button v-if="multipleWorkspaces && canMoveWorker(w)" class="worker-menu-item" @click="rosterMenuMoveTo(w.slot)"><i class="menu-item-icon" data-lucide="arrow-right" aria-hidden="true"></i><span class="menu-item-label">Move to workspace&hellip;</span></button>
                <button class="worker-menu-item worker-menu-danger" @click="rosterMenuDelete(w.slot)"><i class="menu-item-icon" data-lucide="trash-2" aria-hidden="true"></i><span class="menu-item-label">Delete Worker&hellip;</span></button>
              </div>
            </Teleport>
          </div>
        </div>
      </div>
      </div>
    </div>
  `,
  computed: {
    columns() {
      return this.config?.columns || [{ key: 'inbox', label: 'Inbox' }];
    },
    selectedColumnLabel() {
      const col = this.columns.find(c => c.key === this.selectedColumn);
      return col ? col.label : this.selectedColumn;
    },
    filteredTasks() {
      const weight = { urgent: 0, high: 1, normal: 2, low: 3 };
      return (this.tasks || [])
        .filter(t => t.status === this.selectedColumn)
        .sort((a, b) => {
          const pa = weight[a.priority] ?? weight.normal;
          const pb = weight[b.priority] ?? weight.normal;
          if (pa !== pb) return pa - pb;
          return (b.created_at || '').localeCompare(a.created_at || '');
        });
    },
    workerList() {
      if (!this.layout?.slots) return [];
      const slots = this.layout.slots;
      const cols = Number(this.config?.grid?.cols) || 4;

      const entries = [];
      slots.forEach((s, i) => {
        if (!s) return;
        const row = Number.isFinite(Number(s.row)) ? Number(s.row) : Math.floor(i / cols);
        const col = Number.isFinite(Number(s.col)) ? Number(s.col) : (i % cols);
        entries.push({ slot: i, slotData: s, row, col });
      });

      const normName = (n) => String(n || '').trim().toLowerCase().replace(/\s+/g, ' ');
      const byCoord = new Map();
      const byNormalizedName = new Map();
      entries.forEach(e => {
        byCoord.set(`${e.row},${e.col}`, e);
        const n = normName(e.slotData.name);
        if (n && !byNormalizedName.has(n)) byNormalizedName.set(n, e);
      });

      const gridOrder = entries.slice().sort((a, b) => a.row - b.row || a.col - b.col);

      const passTarget = (e) => {
        const disp = String(e.slotData.disposition || '').trim();
        if (!disp) return null;
        if (disp.startsWith('worker:')) {
          return byNormalizedName.get(normName(disp.slice(7))) || null;
        }
        if (disp.startsWith('pass:')) {
          const dir = disp.slice(5).trim().toLowerCase();
          const delta = { up: [-1, 0], down: [1, 0], left: [0, -1], right: [0, 1] }[dir];
          if (!delta) return null;
          return byCoord.get(`${e.row + delta[0]},${e.col + delta[1]}`) || null;
        }
        return null;
      };

      const visited = new Set();
      const ordered = [];

      for (const m of gridOrder) {
        if (m.slotData.type !== 'marker') continue;
        if (visited.has(m.slot)) continue;

        const groupSet = new Set([m.slot]);
        const queue = [m];

        const enqueue = (e) => {
          if (!e || groupSet.has(e.slot) || visited.has(e.slot)) return;
          if (e.slotData.type === 'marker') return;
          groupSet.add(e.slot);
          queue.push(e);
        };

        const sameColBelow = entries
          .filter(e => e.col === m.col && e.row > m.row)
          .sort((a, b) => a.row - b.row);
        let prevColRow = null;
        for (const e of sameColBelow) {
          if (prevColRow !== null && e.row !== prevColRow + 1) break;
          if (e.slotData.type === 'marker') break;
          enqueue(e);
          prevColRow = e.row;
        }

        const members = [];
        while (queue.length) {
          const cur = queue.shift();
          members.push(cur);
          enqueue(passTarget(cur));
        }

        members.sort((a, b) => a.row - b.row || a.col - b.col);
        for (const g of members) {
          if (visited.has(g.slot)) continue;
          visited.add(g.slot);
          ordered.push(g);
        }
      }

      for (const e of gridOrder) {
        if (visited.has(e.slot)) continue;
        visited.add(e.slot);
        ordered.push(e);
      }

      return ordered.map(e => {
        const s = e.slotData;
        return {
          slot: e.slot,
          name: s.name,
          state: s.service_state?.state || s.state || 'idle',
          paused: s.paused === true,
          activation: s.activation,
          retry_at: s.retry_at,
          retry_attempt: s.retry_attempt,
          retry_max: s.retry_max,
          agent: s.agent,
          type: s.type,
          color: s.color,
          service_state: s.service_state,
          port: s.port,
          taskQueueLength: Array.isArray(s.task_queue) ? s.task_queue.length : 0,
        };
      });
    },
    projectIconToken() {
      return (this.projects || [])
        .map(p => `${p.id}:${p.available === false ? 'folder-x' : 'folder'}:${p.id === this.activeWorkspaceId ? 'active' : ''}`)
        .join('|');
    },
    inboxIconToken() {
      return this.filteredTasks.map(task => task.id).join('|');
    },
    workerIconToken() {
      return this.workerList
        .map(worker => `${worker.slot}:${this.workerTypeIcon(worker)}`)
        .join('|');
    },
    rosterWorkerMenuIconToken() {
      if (this.openRosterWorkerMenuSlot === null) return 'closed';
      const worker = this.workerList.find(w => w.slot === this.openRosterWorkerMenuSlot);
      if (!worker) return 'missing';
      return [
        worker.slot,
        this.workerState(worker),
        worker.taskQueueLength,
        this.isPausedWorker(worker) ? 'paused' : 'active',
        this.multipleWorkspaces ? 'workspaces' : 'one-workspace',
        this.serviceSiteUrl(worker) ? 'site' : 'no-site',
      ].join('|');
    },
    rosterWorkerMenuStyle() {
      return { top: this.rosterWorkerMenuPos.top + 'px', left: this.rosterWorkerMenuPos.left + 'px' };
    },
    leftPaneStyle() {
      if (!this.visible) return null;
      return { width: `${this.draggingWidth || this.paneWidth}px` };
    },
    projectCount() {
      return Array.isArray(this.projects) ? this.projects.length : 0;
    }
  },
  watch: {
    columns(cols) {
      if (!cols.some(c => c.key === this.selectedColumn)) {
        this.selectedColumn = 'inbox';
      }
    },
    projectsLoaded: {
      immediate: true,
      handler(loaded) {
        // Only evaluate the empty-state hint once the server has delivered the
        // real project list. The reactive([]) initial value is pre-load and
        // must not be mistaken for "user has zero projects".
        if (!loaded || this.emptyProjectHintInitialized) return;
        this.emptyProjectHintInitialized = true;
        if (this.projectCount === 0 && !this.activeWorkspaceId) {
          this.showProjectMenu = true;
          this.showEmptyProjectHint = true;
          window.dispatchEvent(new Event('bullpen:menu:close-main'));
        }
      }
    },
    projectCount(count) {
      if (count > 0) {
        this.showEmptyProjectHint = false;
        this.showProjectMenu = false;
      }
    },
    activeWorkspaceId(next) {
      if (next) {
        this.showEmptyProjectHint = false;
        this.showProjectMenu = false;
      }
    },
    showProjectMenu(next) {
      if (next) this.$nextTick(() => renderLucideIcons(this.$el));
    },
    projectIconToken() {
      this.$nextTick(() => renderLucideIcons(this.$el));
    },
    inboxIconToken() {
      this.$nextTick(() => renderLucideIcons(this.$el));
    },
    workerIconToken() {
      this.$nextTick(() => renderLucideIcons(this.$el));
    },
    rosterWorkerMenuIconToken() {
      if (this.openRosterWorkerMenuSlot !== null) this.$nextTick(() => this.renderRosterWorkerMenuIcons());
    },
  },
  data() {
    return {
      rosterDragSlot: null,
      projectDragOverId: null,
      openRosterWorkerMenuSlot: null,
      rosterWorkerMenuPos: { top: 0, left: 0 },
      selectedColumn: 'inbox',
      showProjectMenu: false,
      showEmptyProjectHint: false,
      emptyProjectHintInitialized: false,
      paneWidth: LeftPane._loadPaneWidth(),
      resizing: null,
      draggingWidth: null,
    };
  },
  mounted() {
    document.addEventListener('click', this.onGlobalClick);
    window.addEventListener('bullpen:menu:close-projects', this.onExternalCloseProjectMenu);
    renderLucideIcons(this.$el);
  },
  beforeUnmount() {
    document.removeEventListener('click', this.onGlobalClick);
    window.removeEventListener('bullpen:menu:close-projects', this.onExternalCloseProjectMenu);
    this._teardownResizeListeners();
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  },
  methods: {
    toggleProjectMenu() {
      this.showProjectMenu = !this.showProjectMenu;
      this.showEmptyProjectHint = false;
      if (this.showProjectMenu) {
        window.dispatchEvent(new Event('bullpen:menu:close-main'));
      }
    },
    onGlobalClick() {
      this.showProjectMenu = false;
      this.showEmptyProjectHint = false;
      this.closeWorkerMenu();
    },
    onExternalCloseProjectMenu() {
      this.showProjectMenu = false;
      this.showEmptyProjectHint = false;
    },
    dismissEmptyProjectHint() {
      this.showEmptyProjectHint = false;
    },
    onDragStart(e, taskId) {
      window.dispatchEvent(new CustomEvent('bullpen:task-drag:start', { detail: { taskId } }));
      e.dataTransfer.setData(window.BULLPEN_TASK_DND_MIME, taskId);
      e.dataTransfer.setData('text/plain', taskId);
      e.dataTransfer.effectAllowed = 'move';
    },
    onDragEnd(e) {
      const taskId = e?.dataTransfer?.getData?.(window.BULLPEN_TASK_DND_MIME) || window.BULLPEN_TASK_DRAG_TASK_ID;
      window.dispatchEvent(new CustomEvent('bullpen:task-drag:end', { detail: { taskId } }));
    },
    isTaskDragEvent(e) {
      const types = e?.dataTransfer?.types || [];
      return types.includes(window.BULLPEN_TASK_DND_MIME) || (window.BULLPEN_TASK_DRAG_ACTIVE && types.includes('text/plain'));
    },
    taskIdFromDragEvent(e) {
      return e?.dataTransfer?.getData?.(window.BULLPEN_TASK_DND_MIME)
        || (window.BULLPEN_TASK_DRAG_ACTIVE ? e?.dataTransfer?.getData?.('text/plain') : '');
    },
    onProjectDragOver(e, project) {
      if (!project || project.available === false || project.id === this.activeWorkspaceId || !this.isTaskDragEvent(e)) {
        if (e?.dataTransfer) e.dataTransfer.dropEffect = 'none';
        return;
      }
      e.dataTransfer.dropEffect = 'move';
      this.projectDragOverId = project.id;
    },
    onProjectDragLeave(e, project) {
      if (this.projectDragOverId === project?.id) this.projectDragOverId = null;
    },
    onProjectDrop(e, project) {
      const taskId = this.taskIdFromDragEvent(e);
      try {
        if (!project || project.available === false || project.id === this.activeWorkspaceId || !taskId) return;
        this.$emit('move-task-project', { id: taskId, destWorkspaceId: project.id });
      } finally {
        this.projectDragOverId = null;
        if (window.BULLPEN_TASK_DRAG_ACTIVE) {
          window.dispatchEvent(new CustomEvent('bullpen:task-drag:end', { detail: { taskId } }));
        }
      }
    },
    agentColor(agent) {
      return agentColor(agent);
    },
    workerColor(worker) {
      return workerColor(worker);
    },
    workerTypeIcon(worker) {
      return getWorkerTypeIcon(worker);
    },
    workerType(worker) {
      return String(worker?.type || 'ai');
    },
    workerState(worker) {
      return worker?.service_state?.state || worker?.state || 'idle';
    },
    isServiceWorkerType(worker) {
      return typeof isServiceWorker === 'function' ? isServiceWorker(worker) : this.workerType(worker) === 'service';
    },
    isMarkerWorkerType(worker) {
      return typeof isMarkerWorker === 'function' ? isMarkerWorker(worker) : this.workerType(worker) === 'marker';
    },
    isValueWorkerType(worker) {
      return typeof isValueWorker === 'function' ? isValueWorker(worker) : this.workerType(worker) === 'value';
    },
    isEvalWorkerType(worker) {
      return typeof isEvalWorker === 'function' ? isEvalWorker(worker) : this.workerType(worker) === 'eval';
    },
    isUnknownWorkerTypeForRoster(worker) {
      return typeof isUnknownWorkerType === 'function' ? isUnknownWorkerType(worker) : false;
    },
    isDisabledWorkerType(worker) {
      return this.isEvalWorkerType(worker) || this.isUnknownWorkerTypeForRoster(worker);
    },
    isPausedWorker(worker) {
      return worker?.paused === true;
    },
    isWorkingWorker(worker) {
      return ['working', 'retrying', 'starting', 'running', 'healthy', 'unhealthy'].includes(this.workerState(worker));
    },
    canConfigureWorker(worker) {
      return !this.isUnknownWorkerTypeForRoster(worker);
    },
    canStartWorker(worker) {
      if (this.isServiceWorkerType(worker)) return ['idle', 'stopped', 'crashed'].includes(this.workerState(worker));
      if (this.isMarkerWorkerType(worker)) return false;
      if (this.isValueWorkerType(worker)) return false;
      return this.workerState(worker) === 'idle' && !this.isDisabledWorkerType(worker);
    },
    canStopWorker(worker) {
      if (this.isServiceWorkerType(worker)) return ['starting', 'running', 'healthy', 'unhealthy'].includes(this.workerState(worker));
      return this.isWorkingWorker(worker);
    },
    canRestartWorker(worker) {
      return this.isServiceWorkerType(worker) && ['idle', 'stopped', 'running', 'healthy', 'unhealthy', 'crashed'].includes(this.workerState(worker));
    },
    canWatchWorker(worker) {
      return this.isServiceWorkerType(worker) || this.isWorkingWorker(worker);
    },
    canPauseWorker(worker) {
      return !this.isMarkerWorkerType(worker) && !this.isValueWorkerType(worker) && !this.isEvalWorkerType(worker) && !this.isUnknownWorkerTypeForRoster(worker);
    },
    canMoveWorker(worker) {
      return this.workerState(worker) === 'idle' || (this.isServiceWorkerType(worker) && ['stopped', 'crashed'].includes(this.workerState(worker)));
    },
    runMenuLabel(worker) {
      const queueCount = Number(worker?.taskQueueLength || 0);
      if (!this.isServiceWorkerType(worker)) return queueCount > 0 ? `Run next (${queueCount})` : 'Run';
      return queueCount > 0 ? 'Run queued order' : 'Start';
    },
    serviceSiteUrl(worker) {
      return typeof window.getServiceSiteUrl === 'function' ? window.getServiceSiteUrl(worker) : '';
    },
    workerStatusLabel(worker) {
      if (worker?.paused === true) return 'PAUSED';
      const state = this.workerState(worker).toUpperCase();
      if (state === 'IDLE' && worker?.activation === 'manual' && Number(worker?.taskQueueLength || 0) > 0) {
        return 'WAITING FOR RUN';
      }
      if (state === 'RETRYING') {
        const attempt = Number(worker?.retry_attempt || 0);
        const max = Number(worker?.retry_max || 0);
        return attempt && max ? `${state} (${attempt}/${max})` : state;
      }
      if (state !== 'WORKING') return state;
      const queueCount = Math.max(1, Number(worker?.taskQueueLength || 0));
      return `${state} (${queueCount})`;
    },
    workerStatusClass(worker) {
      return this.workerState(worker);
    },
    toggleWorkerMenu(worker, e) {
      if (this.openRosterWorkerMenuSlot === worker.slot) {
        this.closeWorkerMenu();
        return;
      }
      const btn = e?.currentTarget;
      if (btn && typeof btn.getBoundingClientRect === 'function') {
        const rect = btn.getBoundingClientRect();
        const menuWidth = 210;
        let left = rect.right - menuWidth;
        if (left < 4) left = rect.left;
        this.rosterWorkerMenuPos = { top: rect.bottom + 4, left };
      }
      this.openRosterWorkerMenuSlot = worker.slot;
      this.showProjectMenu = false;
      this.showEmptyProjectHint = false;
      window.dispatchEvent(new Event('bullpen:menu:close-main'));
      this.$nextTick(() => {
        this.renderRosterWorkerMenuIcons();
        const [first] = this.workerMenuItems();
        if (first) first.focus();
      });
    },
    closeWorkerMenu() {
      this.openRosterWorkerMenuSlot = null;
    },
    renderRosterWorkerMenuIcons() {
      const menu = Array.isArray(this.$refs.rosterWorkerMenu) ? this.$refs.rosterWorkerMenu[0] : this.$refs.rosterWorkerMenu;
      if (menu) renderLucideIcons(menu);
    },
    workerMenuItems() {
      const menu = Array.isArray(this.$refs.rosterWorkerMenu) ? this.$refs.rosterWorkerMenu[0] : this.$refs.rosterWorkerMenu;
      if (!menu || typeof menu.querySelectorAll !== 'function') return [];
      return Array.from(menu.querySelectorAll('.worker-menu-item:not([disabled])'));
    },
    onWorkerMenuKeydown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        this.closeWorkerMenu();
        return;
      }
      const items = this.workerMenuItems();
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
    rosterMenuEdit(slot) {
      this.closeWorkerMenu();
      this.$emit('configure-worker', slot);
    },
    rosterMenuRun(slot) {
      this.closeWorkerMenu();
      this.$root.startWorkerSlot(slot);
    },
    rosterMenuStop(slot) {
      this.closeWorkerMenu();
      this.$root.stopWorkerSlot(slot);
    },
    rosterMenuRestart(slot) {
      this.closeWorkerMenu();
      this.$root.restartServiceSlot(slot);
    },
    rosterMenuPause(slot) {
      this.closeWorkerMenu();
      this.$root.saveWorkerConfig({ slot, fields: { paused: true } });
    },
    rosterMenuUnpause(slot) {
      this.closeWorkerMenu();
      this.$root.saveWorkerConfig({ slot, fields: { paused: false } });
    },
    rosterMenuDuplicate(slot) {
      this.closeWorkerMenu();
      this.$root.duplicateWorker(slot);
    },
    rosterMenuCopyWorker(slot) {
      this.closeWorkerMenu();
      this.$emit('copy-worker', slot);
    },
    rosterMenuExportWorker(slot) {
      this.closeWorkerMenu();
      this.$root.exportWorker(slot);
    },
    rosterMenuWatch(slot) {
      this.closeWorkerMenu();
      this.$emit('open-focus', slot);
    },
    rosterMenuOpenSite(slot) {
      this.closeWorkerMenu();
      this.$root.openServiceSite(slot);
    },
    rosterMenuCopyTo(slot) {
      this.closeWorkerMenu();
      this.$emit('transfer-worker', { slot, mode: 'copy' });
    },
    rosterMenuMoveTo(slot) {
      this.closeWorkerMenu();
      this.$emit('transfer-worker', { slot, mode: 'move' });
    },
    rosterMenuDelete(slot) {
      this.closeWorkerMenu();
      this.$root.removeWorker(slot);
    },
    unseenCount(wsId) {
      if (!this.workspaces || !this.workspaces[wsId]) return 0;
      return this.workspaces[wsId].unseenActivity || 0;
    },
    canRemoveProject(project) {
      return !!(project && project.id && this.projects && this.projects.length > 1);
    },
    activeWorkspacePath() {
      return this.workspaces?.[this.activeWorkspaceId]?.workspace || '';
    },
    defaultCloneParent() {
      const workspace = this.activeWorkspacePath();
      if (!workspace) return '';
      const parts = workspace.split(/[\\/]+/);
      parts.pop();
      const parent = parts.join('/') || (workspace.startsWith('/') ? '/' : '');
      return parent || '';
    },
    projectEntryRoot() {
      const root = String(this.projectsRoot || '').trim();
      return root || this.defaultCloneParent();
    },
    repoNameFromUrl(url) {
      const trimmed = String(url || '').trim().replace(/\/+$/, '');
      const name = trimmed.split('/').filter(Boolean).pop() || '';
      return name.endsWith('.git') ? name.slice(0, -4) : name;
    },
    confirmRemoveProject(project) {
      const name = project?.name || 'this project';
      if (!project?.id) return;
      if (!confirm(`Remove "${name}" from the project list?\n\nThis only unregisters the project from Bullpen. No project files are deleted.`)) {
        return;
      }
      this.$emit('remove-project', project.id);
    },
    promptAddProject() {
      this.showProjectMenu = false;
      this.showEmptyProjectHint = false;
      const root = this.projectEntryRoot();
      const promptText = root
        ? `Enter project directory under ${root} (name or absolute path):`
        : 'Enter absolute path to project directory:';
      const path = prompt(promptText);
      if (path && path.trim()) {
        this.$emit('add-project', path.trim());
      }
    },
    promptNewProject() {
      this.showProjectMenu = false;
      this.showEmptyProjectHint = false;
      const root = this.projectEntryRoot();
      const promptText = root
        ? `Enter new project directory under ${root} (name or absolute path):`
        : 'Enter absolute path for new project directory:';
      const path = prompt(promptText);
      if (path && path.trim()) {
        this.$emit('new-project', path.trim());
      }
    },
    promptCloneProject() {
      this.showProjectMenu = false;
      this.showEmptyProjectHint = false;
      const url = prompt('Enter Git repository URL:');
      if (!url || !url.trim()) return;
      const repoName = this.repoNameFromUrl(url);
      const defaultPath = this.defaultCloneParent() && repoName ? `${this.defaultCloneParent()}/${repoName}` : '';
      const promptText = defaultPath
        ? `Enter absolute path to clone into (leave empty for ${defaultPath}):`
        : 'Enter absolute path to clone into (leave empty for the server default):';
      const path = prompt(promptText);
      this.$emit('clone-project', { url: url.trim(), path: (path || '').trim() || null });
    },
    onRosterDragOver(e, w) {
      if (!this.rosterWorkerAcceptsTaskDrop(w)) {
        e.dataTransfer.dropEffect = 'none';
        this.rosterDragSlot = null;
        return;
      }
      const types = e.dataTransfer.types;
      if (types.includes(window.BULLPEN_TASK_DND_MIME) || (window.BULLPEN_TASK_DRAG_ACTIVE && types.includes('text/plain'))) {
        e.dataTransfer.dropEffect = 'move';
        this.rosterDragSlot = w.slot;
      }
    },
    onRosterDragLeave() {
      this.rosterDragSlot = null;
    },
    onRosterDrop(e, slot) {
      e.preventDefault();
      this.rosterDragSlot = null;
      const worker = (this.workerList || []).find(w => w.slot === slot);
      const taskId = e.dataTransfer.getData(window.BULLPEN_TASK_DND_MIME)
        || (window.BULLPEN_TASK_DRAG_ACTIVE ? e.dataTransfer.getData('text/plain') : '');
      try {
        if (!this.rosterWorkerAcceptsTaskDrop(worker)) return;
        if (taskId) {
          this.$root.assignTask(taskId, slot);
        }
      } finally {
        if (window.BULLPEN_TASK_DRAG_ACTIVE) {
          window.dispatchEvent(new CustomEvent('bullpen:task-drag:end', { detail: { taskId } }));
        }
      }
    },
    rosterWorkerAcceptsTaskDrop(worker) {
      const type = String(worker?.type || 'ai');
      return !['value', 'eval'].includes(type);
    },
    onResizeDown(e) {
      if (e.button !== 0) return;
      if (this.resizing) return;
      e.preventDefault();
      e.stopPropagation();
      this.resizing = {
        startX: e.clientX,
        startWidth: this.paneWidth,
        pointerId: e.pointerId,
      };
      this.draggingWidth = this.paneWidth;
      this._resizeMoveHandler = (ev) => this.onResizeMove(ev);
      this._resizeUpHandler = (ev) => this.onResizeUp(ev);
      window.addEventListener('pointermove', this._resizeMoveHandler);
      window.addEventListener('pointerup', this._resizeUpHandler);
      window.addEventListener('pointercancel', this._resizeUpHandler);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    },
    onResizeMove(e) {
      if (!this.resizing) return;
      if (e.pointerId !== this.resizing.pointerId) return;
      const dx = e.clientX - this.resizing.startX;
      const next = this.resizing.startWidth + dx;
      this.draggingWidth = LeftPane._clampWidth(Math.round(next));
    },
    onResizeUp(e) {
      if (!this.resizing) return;
      if (e && e.pointerId !== this.resizing.pointerId) return;
      this._teardownResizeListeners();
      const dragged = this.draggingWidth;
      this.resizing = null;
      this.draggingWidth = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      if (dragged != null) {
        this.paneWidth = LeftPane._clampWidth(dragged);
        try {
          localStorage.setItem('bullpen.leftPaneWidth', String(this.paneWidth));
        } catch (e) { /* ignore */ }
      }
    },
    resetWidth() {
      this.paneWidth = 280;
      try {
        localStorage.setItem('bullpen.leftPaneWidth', '280');
      } catch (e) { /* ignore */ }
    },
    _teardownResizeListeners() {
      if (this._resizeMoveHandler) {
        window.removeEventListener('pointermove', this._resizeMoveHandler);
        window.removeEventListener('pointerup', this._resizeUpHandler);
        window.removeEventListener('pointercancel', this._resizeUpHandler);
        this._resizeMoveHandler = null;
        this._resizeUpHandler = null;
      }
    }
  },
  _clampWidth(w) {
    return Math.max(200, Math.min(520, w));
  },
  _loadPaneWidth() {
    try {
      const raw = localStorage.getItem('bullpen.leftPaneWidth');
      if (raw) {
        const n = parseInt(raw, 10);
        if (Number.isFinite(n)) return LeftPane._clampWidth(n);
      }
    } catch (e) { /* ignore */ }
    return 280;
  }
};
