const TaskCreateModal = {
  props: ['visible', 'columns'],
  emits: ['close', 'create'],
  data() {
    return {
      title: '',
      type: 'task',
      priority: 'normal',
      status: 'inbox',
      tags: '',
      description: '',
    };
  },
  computed: {
    writableColumns() {
      const workerColumns = new Set(['assigned', 'in_progress']);
      const columns = (this.columns || [])
        .filter(col => col?.key && !workerColumns.has(col.key))
        .map(col => ({
          key: col.key,
          label: col.label || col.key,
        }));
      return columns.length ? columns : [{ key: 'inbox', label: 'Inbox' }];
    },
    defaultStatus() {
      if (this.writableColumns.some(col => col.key === 'inbox')) return 'inbox';
      return this.writableColumns[0]?.key || 'inbox';
    },
  },
  template: `
    <div v-if="visible" class="modal-overlay" @click.self="$emit('close')" @keydown.escape="$emit('close')" @keydown.meta.enter="onPrimaryShortcut" tabindex="0" ref="overlay">
      <div class="modal">
        <div class="modal-header">
          <h2>New Ticket</h2>
          <button class="btn btn-icon" @click="$emit('close')">&times;</button>
        </div>
        <div class="modal-body">
          <label class="form-label">
            Title
            <input class="form-input" v-model="title" ref="titleInput"
                   @keydown.enter="submit" placeholder="Ticket title" autofocus>
          </label>
          <div class="form-row">
            <label class="form-label">
              Type
              <select class="form-select" v-model="type">
                <option value="task">Task</option>
                <option value="bug">Bug</option>
                <option value="feature">Feature</option>
                <option value="chore">Chore</option>
              </select>
            </label>
            <label class="form-label">
              Priority
              <select class="form-select" v-model="priority">
                <option value="low">Low</option>
                <option value="normal">Normal</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
              </select>
            </label>
          </div>
          <label class="form-label">
            Column
            <select class="form-select" v-model="status">
              <option v-for="col in writableColumns" :key="col.key" :value="col.key">{{ col.label }}</option>
            </select>
          </label>
          <label class="form-label">
            Tags <span class="form-hint">(comma separated)</span>
            <input class="form-input" v-model="tags" placeholder="backend, auth">
          </label>
          <label class="form-label">
            Description
            <textarea class="form-textarea" v-model="description" rows="4"
                      placeholder="Describe the task..."></textarea>
          </label>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="$emit('close')">Cancel</button>
          <button class="btn btn-primary" @click="submit" :disabled="!title.trim()">Create</button>
        </div>
      </div>
    </div>
  `,
  watch: {
    visible(v) {
      if (v) {
        this.title = '';
        this.type = 'task';
        this.priority = 'normal';
        this.status = this.storedStatus();
        this.tags = '';
        this.description = '';
        this.$nextTick(() => this.$refs.titleInput?.focus());
      }
    },
    columns() {
      if (!this.writableColumns.some(col => col.key === this.status)) {
        this.status = this.storedStatus();
      }
    }
  },
  methods: {
    onPrimaryShortcut(e) {
      e.preventDefault();
      this.submit();
    },
    storedStatus() {
      let stored = '';
      try {
        stored = window.localStorage?.getItem('bullpen.newTicket.status') || '';
      } catch (err) {
        stored = '';
      }
      if (stored && this.writableColumns.some(col => col.key === stored)) return stored;
      return this.defaultStatus;
    },
    persistStatus() {
      try {
        window.localStorage?.setItem('bullpen.newTicket.status', this.status || this.defaultStatus);
      } catch (err) {
        // localStorage can be unavailable in private or embedded contexts.
      }
    },
    submit() {
      if (!this.title.trim()) return;
      if (!this.writableColumns.some(col => col.key === this.status)) {
        this.status = this.defaultStatus;
      }
      this.persistStatus();
      const tags = this.tags
        .split(',')
        .map(t => t.trim())
        .filter(Boolean);
      this.$emit('create', {
        title: this.title.trim(),
        type: this.type,
        priority: this.priority,
        status: this.status,
        tags,
        description: this.description,
      });
      this.$emit('close');
    }
  }
};
