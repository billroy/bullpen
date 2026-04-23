const LeftPane = {
  props: ['tasks', 'layout', 'visible', 'config', 'projects', 'projectsLoaded', 'activeWorkspaceId', 'workspaces'],
  emits: ['new-task', 'select-task', 'switch-workspace', 'add-project', 'new-project', 'clone-project', 'remove-project'],
  template: `
    <div class="left-pane" :class="{ collapsed: !visible }">
      <div v-if="projects" class="left-pane-section" :class="{ 'project-add-only': projects.length <= 1 }">
        <div class="section-header">
          <h3>Projects</h3>
          <div class="project-menu-wrap" @click.stop>
            <button class="btn btn-sm" @click="toggleProjectMenu">...</button>
            <div v-if="showEmptyProjectHint" class="project-menu-tooltip" role="status" aria-live="polite">
              Open the menu to add or create your first project.
            </div>
            <div v-if="showProjectMenu" class="project-menu">
              <button class="project-menu-item" @click="promptAddProject"><i class="menu-item-icon" data-lucide="folder-open" aria-hidden="true"></i><span class="menu-item-label">Add Project</span></button>
              <button class="project-menu-item" @click="promptNewProject"><i class="menu-item-icon" data-lucide="folder-plus" aria-hidden="true"></i><span class="menu-item-label">New Project</span></button>
              <button class="project-menu-item" @click="promptCloneProject"><i class="menu-item-icon" data-lucide="git-branch-plus" aria-hidden="true"></i><span class="menu-item-label">Clone from Git</span></button>
            </div>
          </div>
        </div>
        <div v-if="projects.length > 1" class="project-list">
          <div v-for="p in projects" :key="p.id"
               class="project-item"
               :class="{ active: p.id === activeWorkspaceId, unavailable: p.available === false }"
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
      <div class="left-pane-section">
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
      <div class="left-pane-section">
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
            <span class="status-pill" :class="'status-' + (w.state || 'idle')">{{ workerStatusLabel(w) }}</span>
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
      return this.layout.slots
        .map((s, i) => s ? {
          slot: i,
          name: s.name,
          state: s.state || 'idle',
          agent: s.agent,
          type: s.type,
          taskQueueLength: Array.isArray(s.task_queue) ? s.task_queue.length : 0,
        } : null)
        .filter(Boolean);
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
        this.showEmptyProjectHint = Array.isArray(this.projects) && this.projects.length === 0;
      }
    }
  },
  data() {
    return {
      rosterDragSlot: null,
      selectedColumn: 'inbox',
      showProjectMenu: false,
      showEmptyProjectHint: false,
      emptyProjectHintInitialized: false,
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
  },
  updated() {
    renderLucideIcons(this.$el);
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
    },
    onExternalCloseProjectMenu() {
      this.showProjectMenu = false;
      this.showEmptyProjectHint = false;
    },
    onDragStart(e, taskId) {
      window.dispatchEvent(new Event('bullpen:task-drag:start'));
      e.dataTransfer.setData(window.BULLPEN_TASK_DND_MIME, taskId);
      e.dataTransfer.setData('text/plain', taskId);
      e.dataTransfer.effectAllowed = 'move';
    },
    onDragEnd() {
      window.dispatchEvent(new Event('bullpen:task-drag:end'));
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
    workerStatusLabel(worker) {
      const state = (worker?.state || 'idle').toUpperCase();
      if (state !== 'WORKING') return state;
      const queueCount = Math.max(1, Number(worker?.taskQueueLength || 0));
      return `${state} (${queueCount})`;
    },
    unseenCount(wsId) {
      if (!this.workspaces || !this.workspaces[wsId]) return 0;
      return this.workspaces[wsId].unseenActivity || 0;
    },
    canRemoveProject(project) {
      return !!(project && project.id && this.projects && this.projects.length > 1);
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
      const path = prompt('Enter absolute path to project directory:');
      if (path && path.trim()) {
        this.$emit('add-project', path.trim());
      }
    },
    promptNewProject() {
      this.showProjectMenu = false;
      this.showEmptyProjectHint = false;
      const path = prompt('Enter absolute path for new project directory:');
      if (path && path.trim()) {
        this.$emit('new-project', path.trim());
      }
    },
    promptCloneProject() {
      this.showProjectMenu = false;
      this.showEmptyProjectHint = false;
      const url = prompt('Enter Git repository URL:');
      if (!url || !url.trim()) return;
      const path = prompt('Enter absolute path to clone into (leave empty for default):');
      this.$emit('clone-project', { url: url.trim(), path: (path || '').trim() || null });
    },
    onRosterDragOver(e, w) {
      if (e.dataTransfer.types.includes('text/plain')) {
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
      const taskId = e.dataTransfer.getData(window.BULLPEN_TASK_DND_MIME) || e.dataTransfer.getData('text/plain');
      if (taskId) {
        this.$root.assignTask(taskId, slot);
      }
    }
  }
};
