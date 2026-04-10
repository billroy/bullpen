const KanbanTab = {
  props: ['tasks', 'columns', 'layout', 'viewMode'],
  emits: ['select-task', 'move-task', 'archive-done', 'new-task'],
  components: { TaskCard },
  template: `
    <div v-if="viewMode !== 'list'" class="kanban-board">
      <div v-for="(col, colIdx) in columns" :key="col.key" class="kanban-column"
           @dragover.prevent="onDragOver($event, col.key)"
           @dragleave="onDragLeave($event)"
           @drop="onDrop($event, col.key)">
        <div class="kanban-column-header" :style="{ borderTopColor: col.color }">
          <span class="column-label">{{ col.label }}</span>
          <span class="column-count">{{ columnTasks(col.key).length }}</span>
          <button v-if="colIdx === 0"
                  class="btn btn-sm column-new-btn"
                  @click="$emit('new-task')"
                  title="Create new ticket">+ New Ticket</button>
          <button v-if="col.key === 'done' && columnTasks(col.key).length"
                  class="btn btn-sm column-archive-btn"
                  @click="$emit('archive-done')"
                  title="Archive all done tickets">Archive</button>
        </div>
        <div class="kanban-column-body">
          <div v-if="columnTasks(col.key).length === 0" class="empty-state kanban-drop-zone">—</div>
          <TaskCard
            v-for="task in columnTasks(col.key)"
            :key="task.id"
            :task="task"
            :layout="layout"
            @select-task="$emit('select-task', $event)"
          />
        </div>
      </div>
    </div>
    <div v-else class="ticket-list">
      <table class="ticket-list-table">
        <thead>
          <tr>
            <th class="ticket-list-col-priority ticket-list-th-sortable" @click="setSort('priority')">
              Priority<span class="sort-indicator">{{ sortIndicator('priority') }}</span>
            </th>
            <th class="ticket-list-col-title ticket-list-th-sortable" @click="setSort('title')">
              Title<span class="sort-indicator">{{ sortIndicator('title') }}</span>
            </th>
            <th class="ticket-list-col-status ticket-list-th-sortable" @click="setSort('status')">
              Status<span class="sort-indicator">{{ sortIndicator('status') }}</span>
            </th>
            <th class="ticket-list-col-type ticket-list-th-sortable" @click="setSort('type')">
              Type<span class="sort-indicator">{{ sortIndicator('type') }}</span>
            </th>
            <th class="ticket-list-col-worker ticket-list-th-sortable" @click="setSort('assigned')">
              Assigned<span class="sort-indicator">{{ sortIndicator('assigned') }}</span>
            </th>
            <th class="ticket-list-col-date ticket-list-th-sortable" @click="setSort('created_at')">
              Created<span class="sort-indicator">{{ sortIndicator('created_at') }}</span>
            </th>
            <th class="ticket-list-col-tokens ticket-list-th-sortable" @click="setSort('tokens')">
              Tokens<span class="sort-indicator">{{ sortIndicator('tokens') }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="sortedTasks.length === 0">
            <td colspan="7" class="ticket-list-empty">No tickets</td>
          </tr>
          <tr
            v-for="task in sortedTasks"
            :key="task.id"
            class="ticket-list-row"
            @click="$emit('select-task', task.id)"
          >
            <td class="ticket-list-col-priority">
              <span class="badge" :class="'priority-' + (task.priority || 'normal')">{{ task.priority || 'normal' }}</span>
            </td>
            <td class="ticket-list-col-title">{{ task.title }}</td>
            <td class="ticket-list-col-status">
              <span class="ticket-list-status-pill" :class="'status-col-' + task.status">{{ columnLabel(task.status) }}</span>
            </td>
            <td class="ticket-list-col-type">
              <span class="badge type-badge" :class="'type-' + (task.type || 'task')">{{ task.type || 'task' }}</span>
            </td>
            <td class="ticket-list-col-worker">{{ workerName(task) || '—' }}</td>
            <td class="ticket-list-col-date">{{ formatDate(task.created_at) }}</td>
            <td class="ticket-list-col-tokens">{{ task.tokens ? formatTokens(task.tokens) : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
  data() {
    return {
      sortField: 'status',
      sortDir: 'asc',
    };
  },
  computed: {
    sortedTasks() {
      const weight = { urgent: 0, high: 1, normal: 2, low: 3 };
      const colOrder = {};
      (this.columns || []).forEach((c, i) => { colOrder[c.key] = i; });
      const dir = this.sortDir === 'asc' ? 1 : -1;
      return (this.tasks || []).slice().sort((a, b) => {
        let cmp = 0;
        switch (this.sortField) {
          case 'status': {
            const ca = colOrder[a.status] ?? 99;
            const cb = colOrder[b.status] ?? 99;
            cmp = ca - cb;
            if (cmp === 0) {
              const pa = weight[a.priority] ?? weight.normal;
              const pb = weight[b.priority] ?? weight.normal;
              cmp = pa - pb;
            }
            break;
          }
          case 'priority': {
            const pa = weight[a.priority] ?? weight.normal;
            const pb = weight[b.priority] ?? weight.normal;
            cmp = pa - pb;
            break;
          }
          case 'title':
            cmp = (a.title || '').localeCompare(b.title || '');
            break;
          case 'type':
            cmp = (a.type || '').localeCompare(b.type || '');
            break;
          case 'assigned': {
            const wa = this.workerName(a) || '';
            const wb = this.workerName(b) || '';
            cmp = wa.localeCompare(wb);
            break;
          }
          case 'created_at':
            cmp = (a.created_at || '').localeCompare(b.created_at || '');
            break;
          case 'tokens':
            cmp = (a.tokens || 0) - (b.tokens || 0);
            break;
        }
        if (cmp === 0) cmp = (a.order || '').localeCompare(b.order || '');
        return cmp * dir;
      });
    }
  },
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
    setSort(field) {
      if (this.sortField === field) {
        this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        this.sortField = field;
        this.sortDir = (field === 'created_at' || field === 'tokens') ? 'desc' : 'asc';
      }
    },
    sortIndicator(field) {
      if (this.sortField !== field) return '';
      return this.sortDir === 'asc' ? ' ↑' : ' ↓';
    },
    formatDate(iso) {
      if (!iso) return '—';
      const d = new Date(iso);
      if (isNaN(d)) return '—';
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    },
    columnLabel(key) {
      const col = (this.columns || []).find(c => c.key === key);
      return col ? col.label : key;
    },
    formatTokens(n) {
      if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
      if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
      return String(n);
    },
    workerName(task) {
      if (task.assigned_to == null) return null;
      const slot = parseInt(task.assigned_to, 10);
      if (isNaN(slot)) return null;
      return this.layout?.slots?.[slot]?.name || null;
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
