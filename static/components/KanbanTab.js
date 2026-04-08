const KanbanTab = {
  props: ['tasks', 'columns', 'layout', 'viewMode'],
  emits: ['select-task', 'move-task', 'archive-done'],
  components: { TaskCard },
  template: `
    <div v-if="viewMode !== 'list'" class="kanban-board">
      <div v-for="col in columns" :key="col.key" class="kanban-column"
           @dragover.prevent="onDragOver($event, col.key)"
           @dragleave="onDragLeave($event)"
           @drop="onDrop($event, col.key)">
        <div class="kanban-column-header" :style="{ borderTopColor: col.color }">
          <span class="column-label">{{ col.label }}</span>
          <span class="column-count">{{ columnTasks(col.key).length }}</span>
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
            <th class="ticket-list-col-priority">Priority</th>
            <th class="ticket-list-col-title">Title</th>
            <th class="ticket-list-col-status">Status</th>
            <th class="ticket-list-col-type">Type</th>
            <th class="ticket-list-col-worker">Assigned</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="sortedTasks.length === 0">
            <td colspan="5" class="ticket-list-empty">No tickets</td>
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
            <td class="ticket-list-col-status">{{ columnLabel(task.status) }}</td>
            <td class="ticket-list-col-type">
              <span class="badge type-badge" :class="'type-' + (task.type || 'task')">{{ task.type || 'task' }}</span>
            </td>
            <td class="ticket-list-col-worker">{{ workerName(task) || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
  computed: {
    sortedTasks() {
      const weight = { urgent: 0, high: 1, normal: 2, low: 3 };
      const colOrder = {};
      (this.columns || []).forEach((c, i) => { colOrder[c.key] = i; });
      return (this.tasks || []).slice().sort((a, b) => {
        const ca = colOrder[a.status] ?? 99;
        const cb = colOrder[b.status] ?? 99;
        if (ca !== cb) return ca - cb;
        const pa = weight[a.priority] ?? weight.normal;
        const pb = weight[b.priority] ?? weight.normal;
        if (pa !== pb) return pa - pb;
        return (a.order || '').localeCompare(b.order || '');
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
    columnLabel(key) {
      const col = (this.columns || []).find(c => c.key === key);
      return col ? col.label : key;
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
