const TaskDetailPanel = {
  props: ['task', 'columns'],
  emits: ['close', 'update', 'delete', 'archive', 'clear-output'],
  data() {
    return {
      editing: false,
      editBody: '',
    };
  },
  computed: {
    agentOutput() {
      if (!this.task?.body) return '';
      const marker = '## Agent Output';
      const idx = this.task.body.indexOf(marker);
      if (idx < 0) return '';
      return this.task.body.substring(idx + marker.length).trim();
    },
    bodyWithoutOutput() {
      if (!this.task?.body) return '';
      const marker = '## Agent Output';
      const idx = this.task.body.indexOf(marker);
      if (idx < 0) return this.task.body;
      return this.task.body.substring(0, idx).trim();
    },
    renderedBody() {
      if (!this.bodyWithoutOutput) return '<p class="empty-state">No description</p>';
      return window.markdownit({ html: false }).render(this.bodyWithoutOutput);
    }
  },
  watch: {
    'task.id'() {
      this.editing = false;
    }
  },
  template: `
    <div v-if="task" class="detail-panel">
      <div class="detail-header">
        <h2 class="detail-title">{{ task.title }}</h2>
        <button class="btn btn-icon" @click="$emit('close')">&times;</button>
      </div>

      <div class="detail-meta">
        <label class="form-label form-label-inline">
          Status
          <select class="form-select" :value="task.status"
                  @change="$emit('update', { id: task.id, status: $event.target.value })">
            <option v-for="col in columns" :key="col.key" :value="col.key">{{ col.label }}</option>
          </select>
        </label>
        <label class="form-label form-label-inline">
          Type
          <select class="form-select" :value="task.type"
                  @change="$emit('update', { id: task.id, type: $event.target.value })">
            <option value="task">Task</option>
            <option value="bug">Bug</option>
            <option value="feature">Feature</option>
            <option value="chore">Chore</option>
          </select>
        </label>
        <label class="form-label form-label-inline">
          Priority
          <select class="form-select" :value="task.priority"
                  @change="$emit('update', { id: task.id, priority: $event.target.value })">
            <option value="low">Low</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </select>
        </label>
      </div>

      <div class="detail-tags" v-if="task.tags && task.tags.length">
        <span class="badge type-badge" v-for="tag in task.tags" :key="tag">{{ tag }}</span>
      </div>

      <div class="detail-id">
        <code>{{ task.id }}</code>
      </div>

      <div class="detail-body">
        <div class="detail-section-header">
          <h3>Description</h3>
          <button class="btn btn-sm" @click="toggleEdit">{{ editing ? 'Preview' : 'Edit' }}</button>
        </div>
        <div v-if="editing">
          <textarea class="form-textarea detail-editor" v-model="editBody" rows="12"></textarea>
          <div class="detail-edit-actions">
            <button class="btn btn-sm" @click="cancelEdit">Cancel</button>
            <button class="btn btn-sm btn-primary" @click="saveEdit">Save</button>
          </div>
        </div>
        <div v-else class="detail-rendered" v-html="renderedBody"></div>
      </div>

      <div class="detail-output" v-if="agentOutput">
        <div class="detail-section-header">
          <h3>Agent Output</h3>
          <button class="btn btn-sm btn-danger" @click="$emit('clear-output', task.id)">Clear</button>
        </div>
        <pre class="detail-output-content">{{ agentOutput }}</pre>
      </div>

      <div class="detail-footer">
        <button class="btn btn-danger btn-sm" @click="confirmDelete">Delete Task</button>
        <button v-if="task.status === 'done'" class="btn btn-sm" @click="$emit('archive', task.id); $emit('close')">Archive</button>
      </div>
    </div>
  `,
  methods: {
    toggleEdit() {
      if (!this.editing) {
        this.editBody = this.bodyWithoutOutput;
        this.editing = true;
      } else {
        this.editing = false;
      }
    },
    cancelEdit() {
      this.editing = false;
    },
    saveEdit() {
      let newBody = this.editBody;
      // Preserve agent output if any
      if (this.agentOutput) {
        newBody = newBody.trimEnd() + '\n\n## Agent Output\n' + this.agentOutput;
      }
      this.$emit('update', { id: this.task.id, body: newBody });
      this.editing = false;
    },
    confirmDelete() {
      if (confirm('Delete this task? This cannot be undone.')) {
        this.$emit('delete', this.task.id);
        this.$emit('close');
      }
    }
  }
};
