const DirectoryPicker = {
  props: ['visible'],
  emits: ['select', 'close'],
  template: `
    <div v-if="visible" class="modal-overlay" @click.self="$emit('close')" @keydown.escape="$emit('close')" tabindex="0" ref="overlay">
      <div class="modal modal-wide">
        <div class="modal-header">
          <h2>Select Project Directory</h2>
          <button class="btn btn-sm" @click="$emit('close')">&times;</button>
        </div>
        <div class="modal-body">
          <div class="dir-picker-path">
            <input class="input" v-model="pathInput" @keydown.enter="goToPath" placeholder="/path/to/project" ref="pathField" />
            <button class="btn btn-sm" @click="goToPath">Go</button>
          </div>
          <div class="dir-picker-list" ref="listEl">
            <div v-if="currentPath !== '/'" class="dir-picker-item dir-picker-parent" @click="goUp">
              <span class="dir-icon">&#x1F4C1;</span> ..
            </div>
            <div v-if="loading" class="dir-picker-loading">Loading...</div>
            <div v-else-if="error" class="dir-picker-error">{{ error }}</div>
            <template v-else>
              <div v-if="dirs.length === 0" class="dir-picker-empty">No subdirectories</div>
              <div v-for="d in dirs" :key="d"
                   class="dir-picker-item"
                   @click="enterDir(d)"
                   @dblclick="selectDir(d)">
                <span class="dir-icon">&#x1F4C1;</span> {{ d }}
              </div>
            </template>
          </div>
        </div>
        <div class="modal-footer">
          <div class="dir-picker-current">{{ currentPath }}</div>
          <div class="modal-footer-right">
            <button class="btn" @click="$emit('close')">Cancel</button>
            <button class="btn btn-primary" @click="selectCurrent">Select This Directory</button>
          </div>
        </div>
      </div>
    </div>
  `,
  data() {
    return {
      currentPath: '',
      pathInput: '',
      dirs: [],
      loading: false,
      error: null,
    };
  },
  watch: {
    visible(v) {
      if (v) {
        this.browse('~');
        this.$nextTick(() => {
          if (this.$refs.overlay) this.$refs.overlay.focus();
        });
      }
    }
  },
  methods: {
    async browse(path) {
      this.loading = true;
      this.error = null;
      try {
        const res = await fetch('/api/browse?path=' + encodeURIComponent(path));
        const data = await res.json();
        if (data.error) {
          this.error = data.error;
        } else {
          this.currentPath = data.path;
          this.pathInput = data.path;
          this.dirs = data.dirs;
        }
      } catch (e) {
        this.error = 'Failed to browse directory';
      } finally {
        this.loading = false;
        if (this.$refs.listEl) this.$refs.listEl.scrollTop = 0;
      }
    },
    enterDir(name) {
      this.browse(this.currentPath + '/' + name);
    },
    goUp() {
      const parent = this.currentPath.replace(/\/[^/]+$/, '') || '/';
      this.browse(parent);
    },
    goToPath() {
      if (this.pathInput.trim()) {
        this.browse(this.pathInput.trim());
      }
    },
    selectCurrent() {
      this.$emit('select', this.currentPath);
      this.$emit('close');
    },
    selectDir(name) {
      this.$emit('select', this.currentPath + '/' + name);
      this.$emit('close');
    }
  }
};
