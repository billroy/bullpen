const TaskDetailPanel = {
  props: ['task', 'columns'],
  emits: ['close', 'update', 'delete', 'archive', 'clear-output'],
  data() {
    return {
      editing: false,
      editBody: '',
      editingTitle: false,
      editTitle: '',
      editingTags: false,
      editTagsValue: '',
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
      this.editingTitle = false;
      this.editingTags = false;
    }
  },
  template: `
    <div v-if="task" class="detail-panel">
      <div class="detail-header">
        <div v-if="editingTitle" class="detail-title-edit">
          <input class="form-input detail-title-input" v-model="editTitle"
                 @keyup.enter="saveTitle" @keyup.escape="cancelTitle" ref="titleInput" />
          <div class="detail-title-actions">
            <button class="btn btn-sm" @click="cancelTitle">Cancel</button>
            <button class="btn btn-sm btn-primary" @click="saveTitle">Save</button>
          </div>
        </div>
        <h2 v-else class="detail-title" @click="startEditTitle" title="Click to edit">{{ task.title }}</h2>
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
            <option value="task">Ticket</option>
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

      <div class="detail-tags-section">
        <div v-if="editingTags">
          <input class="form-input" v-model="editTagsValue" placeholder="comma-separated tags"
                 @keyup.enter="saveTags" @keyup.escape="cancelTags" />
          <div class="detail-edit-actions">
            <button class="btn btn-sm" @click="cancelTags">Cancel</button>
            <button class="btn btn-sm btn-primary" @click="saveTags">Save</button>
          </div>
        </div>
        <div v-else class="detail-tags">
          <span class="badge type-badge" v-for="tag in task.tags" :key="tag">{{ tag }}</span>
          <button class="btn btn-sm" @click="startEditTags">{{ task.tags && task.tags.length ? 'Edit Tags' : 'Add Tags' }}</button>
        </div>
      </div>

      <div class="detail-id">
        <code>{{ task.id }}</code>
        <span v-if="task.tokens" class="token-count" title="Total tokens used by agents">{{ formatTokens(task.tokens) }}</span>
      </div>

      <div class="detail-body">
        <div class="detail-section-header">
          <h3>Description</h3>
          <button class="btn btn-sm" @click="toggleEdit">{{ editing ? 'Preview' : 'Edit' }}</button>
        </div>
        <div v-if="editing">
          <textarea class="form-textarea detail-editor" v-model="editBody" rows="12" @keydown.meta.enter="saveEdit" @keydown.ctrl.enter="saveEdit"></textarea>
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
        <button class="btn btn-danger btn-sm" @click="confirmDelete">Delete Ticket</button>
        <button v-if="task.status === 'done'" class="btn btn-sm" @click="$emit('archive', task.id); $emit('close')">Archive</button>
      </div>
    </div>
  `,
  methods: {
    startEditTitle() {
      this.editTitle = this.task.title;
      this.editingTitle = true;
      this.$nextTick(() => this.$refs.titleInput?.focus());
    },
    saveTitle() {
      const title = this.editTitle.trim();
      if (title && title !== this.task.title) {
        this.$emit('update', { id: this.task.id, title });
      }
      this.editingTitle = false;
    },
    cancelTitle() {
      this.editingTitle = false;
    },
    startEditTags() {
      this.editTagsValue = (this.task.tags || []).join(', ');
      this.editingTags = true;
    },
    saveTags() {
      const tags = this.editTagsValue.split(',').map(t => t.trim()).filter(Boolean);
      this.$emit('update', { id: this.task.id, tags });
      this.editingTags = false;
    },
    cancelTags() {
      this.editingTags = false;
    },
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
    },
    formatTokens(n) {
      if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M tok';
      if (n >= 1000) return (n / 1000).toFixed(1) + 'k tok';
      return n + ' tok';
    }
  }
};
