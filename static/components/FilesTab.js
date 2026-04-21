// Shared fetch wrapper that redirects to /login on a 401. Returning null
// lets callers bail out early without crashing on res.json().
async function filesFetch(input, init) {
  const res = await fetch(input, init);
  if (res.status === 401) {
    window.location = '/login?next=' +
      encodeURIComponent(window.location.pathname + window.location.search);
    return null;
  }
  return res;
}

const FileTreeNode = {
  name: 'FileTreeNode',
  props: ['node', 'depth', 'activePath'],
  emits: ['select'],
  template: `
    <div>
      <div
        class="tree-node"
        :class="{ active: node.path === activePath, directory: isDir }"
        :style="{ paddingLeft: (depth * 16 + 8) + 'px' }"
        @click="onClick"
      >
        <span class="tree-icon">{{ isDir ? (expanded ? '&#9660;' : '&#9654;') : '&#9679;' }}</span>
        <span class="tree-name">{{ node.name }}</span>
      </div>
      <div v-if="isDir && expanded">
        <FileTreeNode
          v-for="child in node.children"
          :key="child.path"
          :node="child"
          :depth="depth + 1"
          :active-path="activePath"
          @select="$emit('select', $event)"
        />
      </div>
    </div>
  `,
  data() {
    return { expanded: false };
  },
  computed: {
    isDir() { return this.node.type === 'dir'; },
  },
  methods: {
    onClick() {
      if (this.isDir) {
        this.expanded = !this.expanded;
      } else {
        this.$emit('select', this.node);
      }
    },
  },
};

const FilesTab = {
  props: ['filesVersion', 'workspaceId'],
  template: `
    <div class="files-container">
      <div class="files-tree-pane">
        <div class="files-tree-header">Workspace Files</div>
        <div class="files-tree-body" v-if="tree.length">
          <FileTreeNode
            v-for="node in tree"
            :key="node.path"
            :node="node"
            :depth="0"
            :active-path="activeFile?.path"
            @select="openFile"
          />
        </div>
        <div v-else class="empty-state">Loading...</div>
      </div>
      <div class="files-viewer-pane">
        <div class="files-tab-bar" v-if="openFiles.length">
          <div
            v-for="f in openFiles"
            :key="f.path"
            class="file-tab"
            :class="{ active: activeFile?.path === f.path }"
            @click="switchToFile(f)"
          >
            <span class="file-tab-name">{{ f.name }}</span>
            <button class="file-tab-close" @click.stop="closeFile(f.path)">&times;</button>
          </div>
        </div>
        <div class="files-viewer-body" v-if="activeFile">
          <!-- Editor toolbar -->
          <div v-if="canEdit" class="file-editor-toolbar">
            <button v-if="!editing" class="btn btn-sm" @click="startEditing">Edit</button>
            <template v-if="editing">
              <button class="btn btn-sm btn-primary" @click="saveEdit">Save</button>
              <button class="btn btn-sm" @click="cancelEdit">Cancel</button>
            </template>
          </div>
          <!-- Edit mode -->
          <div v-if="editing" class="file-edit-container">
            <div v-if="showFind" class="find-replace-bar">
              <div class="find-replace-row">
                <input class="find-input" v-model="findText" placeholder="Find" ref="findInput" @keydown.enter="findNext" @keydown.esc="closeFind" @input="updateFindCount" />
                <span class="find-count">{{ findText ? findIndex + ' / ' + findCount : '' }}</span>
                <button class="btn btn-sm" @click="findPrev" title="Previous">&#9650;</button>
                <button class="btn btn-sm" @click="findNext" title="Next">&#9660;</button>
                <button class="btn btn-sm" @click="closeFind" title="Close">&times;</button>
              </div>
              <div v-if="showReplace" class="find-replace-row">
                <input class="find-input" v-model="replaceText" placeholder="Replace" @keydown.esc="closeFind" />
                <button class="btn btn-sm" @click="doReplace">Replace</button>
                <button class="btn btn-sm" @click="doReplaceAll">Replace All</button>
              </div>
            </div>
            <textarea class="file-editor-textarea" v-model="editContent" ref="editTextarea" @keydown="onEditorKeydown"></textarea>
          </div>
          <!-- Image -->
          <div v-else-if="isImage" class="file-view-image">
            <img :src="'/api/files/' + activeFile.path" :alt="activeFile.name" />
          </div>
          <!-- PDF -->
          <div v-else-if="isPdf" class="file-view-pdf">
            <embed :src="'/api/files/' + activeFile.path + '?raw=1'" type="application/pdf" width="100%" height="100%" />
          </div>
          <!-- HTML preview -->
          <div v-else-if="isHtml" class="file-view-html">
            <div class="file-view-toggle">
              <button class="btn btn-sm" :class="{ active: viewMode === 'preview' }" @click="viewMode = 'preview'">Preview</button>
              <button class="btn btn-sm" :class="{ active: viewMode === 'source' }" @click="viewMode = 'source'">Source</button>
            </div>
            <iframe v-if="viewMode === 'preview'" sandbox :srcdoc="activeFile.content" class="html-iframe"></iframe>
            <pre v-else class="file-source"><code v-html="highlightedCode"></code></pre>
          </div>
          <!-- Markdown -->
          <div v-else-if="isMarkdown" class="file-view-markdown">
            <div class="file-view-toggle">
              <button class="btn btn-sm" :class="{ active: viewMode === 'preview' }" @click="viewMode = 'preview'">Preview</button>
              <button class="btn btn-sm" :class="{ active: viewMode === 'source' }" @click="viewMode = 'source'">Source</button>
            </div>
            <div v-if="viewMode === 'preview'" class="markdown-body" v-html="renderedMarkdown"></div>
            <pre v-else class="file-source"><code v-html="highlightedCode"></code></pre>
          </div>
          <!-- Source code -->
          <div v-else class="file-view-source">
            <pre class="file-source"><code v-html="highlightedCode"></code></pre>
          </div>
        </div>
        <div v-else class="files-viewer-empty">
          <div class="empty-state">Select a file to view</div>
        </div>
      </div>
    </div>
  `,
  components: { FileTreeNode },
  data() {
    return {
      tree: [],
      openFiles: [],
      activeFile: null,
      viewMode: 'preview',
      editing: false,
      editContent: '',
      showFind: false,
      showReplace: false,
      findText: '',
      replaceText: '',
      findCount: 0,
      findIndex: 0,
    };
  },
  computed: {
    ext() {
      if (!this.activeFile) return '';
      const name = this.activeFile.name;
      const dot = name.lastIndexOf('.');
      return dot >= 0 ? name.substring(dot).toLowerCase() : '';
    },
    isImage() {
      return ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp'].includes(this.ext);
    },
    isPdf() {
      return this.ext === '.pdf';
    },
    isHtml() {
      return this.ext === '.html' || this.ext === '.htm';
    },
    isMarkdown() {
      return this.ext === '.md';
    },
    isTextFile() {
      return !this.isImage && !this.isPdf;
    },
    canEdit() {
      if (!this.activeFile || !this.isTextFile) return false;
      // Size guard: skip if content > 1MB
      if (this.activeFile.content && this.activeFile.content.length > 1_000_000) return false;
      return true;
    },
    renderedMarkdown() {
      if (!this.activeFile?.content) return '';
      const md = window.markdownit({ html: false, linkify: true, typographer: true });
      return md.render(this.activeFile.content);
    },
    prismLang() {
      const map = {
        '.js': 'javascript', '.mjs': 'javascript', '.jsx': 'javascript',
        '.ts': 'javascript', '.tsx': 'javascript',
        '.py': 'python',
        '.json': 'json',
        '.css': 'css', '.scss': 'css',
        '.sh': 'bash', '.bash': 'bash', '.zsh': 'bash',
        '.html': 'markup', '.htm': 'markup', '.xml': 'markup', '.svg': 'markup',
        '.md': 'markdown',
      };
      return map[this.ext] || null;
    },
    highlightedCode() {
      if (!this.activeFile?.content) return '';
      const lang = this.prismLang;
      if (lang && Prism.languages[lang]) {
        return Prism.highlight(this.activeFile.content, Prism.languages[lang], lang);
      }
      return this.escapeHtml(this.activeFile.content);
    },
  },
  watch: {
    activeFile() {
      this.viewMode = 'preview';
      this.editing = false;
    },
    filesVersion() {
      this.loadTree();
      if (this.activeFile && !this.editing) {
        this.reloadActiveFile();
      }
    },
    workspaceId(newId, oldId) {
      if (newId === oldId) return;
      this.openFiles = [];
      this.activeFile = null;
      this.editing = false;
      this.loadTree();
    },
  },
  mounted() {
    this.loadTree();
  },
  methods: {
    _filesUrl(path) {
      const base = path ? '/api/files/' + encodeURI(path) : '/api/files';
      return this.workspaceId ? base + '?workspaceId=' + encodeURIComponent(this.workspaceId) : base;
    },
    async loadTree() {
      try {
        const res = await filesFetch(this._filesUrl());
        if (!res) return;
        this.tree = await res.json();
      } catch (e) {
        console.error('Failed to load file tree', e);
      }
    },
    async openFile(node) {
      if (node.type !== 'file') return;
      const ext = this.getExt(node.name);
      const existing = this.openFiles.find(f => f.path === node.path);
      if (existing) {
        this.activeFile = existing;
        // Re-fetch content from disk unless currently editing
        if (!this.editing) this.reloadActiveFile();
        return;
      }
      // Images/PDFs don't need content fetch
      if (['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.pdf'].includes(ext)) {
        const file = { path: node.path, name: node.name, content: null };
        this.openFiles.push(file);
        this.activeFile = file;
        return;
      }
      try {
        const res = await filesFetch(this._filesUrl(node.path));
        if (!res) return;
        if (!res.ok) throw new Error('Failed to load');
        const data = await res.json();
        const file = { path: node.path, name: node.name, content: data.content };
        this.openFiles.push(file);
        this.activeFile = file;
      } catch (e) {
        console.error('Failed to open file', e);
      }
    },
    switchToFile(f) {
      if (this.editing) {
        if (!confirm('Discard unsaved changes?')) return;
        this.editing = false;
      }
      this.activeFile = f;
      this.reloadActiveFile();
    },
    closeFile(path) {
      if (this.editing && this.activeFile?.path === path) {
        if (!confirm('Discard unsaved changes?')) return;
        this.editing = false;
      }
      const idx = this.openFiles.findIndex(f => f.path === path);
      if (idx < 0) return;
      this.openFiles.splice(idx, 1);
      if (this.activeFile?.path === path) {
        this.activeFile = this.openFiles[Math.min(idx, this.openFiles.length - 1)] || null;
      }
    },
    startEditing() {
      this.editContent = this.activeFile.content || '';
      this.editing = true;
    },
    async saveEdit() {
      try {
        const res = await filesFetch(this._filesUrl(this.activeFile.path), {
          method: 'PUT',
          headers: { 'Content-Type': 'text/plain' },
          body: this.editContent,
        });
        if (!res) return;
        if (!res.ok) {
          const data = await res.json();
          alert('Save failed: ' + (data.error || 'Unknown error'));
          return;
        }
        this.activeFile.content = this.editContent;
        this.editing = false;
      } catch (e) {
        alert('Save failed: ' + e.message);
      }
    },
    cancelEdit() {
      this.editing = false;
      this.closeFind();
    },
    onEditorKeydown(e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        this.showFind = true;
        this.showReplace = false;
        this.$nextTick(() => this.$refs.findInput?.focus());
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'h') {
        e.preventDefault();
        this.showFind = true;
        this.showReplace = true;
        this.$nextTick(() => this.$refs.findInput?.focus());
      }
    },
    closeFind() {
      this.showFind = false;
      this.showReplace = false;
      this.findText = '';
      this.replaceText = '';
      this.findCount = 0;
      this.findIndex = 0;
    },
    updateFindCount() {
      if (!this.findText) {
        this.findCount = 0;
        this.findIndex = 0;
        return;
      }
      const matches = this.editContent.split(this.findText).length - 1;
      this.findCount = matches;
      this.findIndex = matches > 0 ? 1 : 0;
    },
    findNext() {
      if (!this.findText || this.findCount === 0) return;
      const ta = this.$refs.editTextarea;
      const start = (ta.selectionEnd || 0);
      const idx = this.editContent.indexOf(this.findText, start);
      if (idx >= 0) {
        ta.focus();
        ta.setSelectionRange(idx, idx + this.findText.length);
        this.findIndex = this._matchIndexAt(idx);
      } else {
        // Wrap around
        const wrapIdx = this.editContent.indexOf(this.findText);
        if (wrapIdx >= 0) {
          ta.focus();
          ta.setSelectionRange(wrapIdx, wrapIdx + this.findText.length);
          this.findIndex = 1;
        }
      }
    },
    findPrev() {
      if (!this.findText || this.findCount === 0) return;
      const ta = this.$refs.editTextarea;
      const end = (ta.selectionStart || this.editContent.length) - 1;
      const idx = this.editContent.lastIndexOf(this.findText, end);
      if (idx >= 0) {
        ta.focus();
        ta.setSelectionRange(idx, idx + this.findText.length);
        this.findIndex = this._matchIndexAt(idx);
      } else {
        // Wrap around
        const wrapIdx = this.editContent.lastIndexOf(this.findText);
        if (wrapIdx >= 0) {
          ta.focus();
          ta.setSelectionRange(wrapIdx, wrapIdx + this.findText.length);
          this.findIndex = this.findCount;
        }
      }
    },
    _matchIndexAt(pos) {
      const before = this.editContent.substring(0, pos);
      return before.split(this.findText).length;
    },
    doReplace() {
      if (!this.findText || this.findCount === 0) return;
      const ta = this.$refs.editTextarea;
      const selected = this.editContent.substring(ta.selectionStart, ta.selectionEnd);
      if (selected === this.findText) {
        this.editContent = this.editContent.substring(0, ta.selectionStart) + this.replaceText + this.editContent.substring(ta.selectionEnd);
        this.updateFindCount();
        this.findNext();
      } else {
        this.findNext();
      }
    },
    doReplaceAll() {
      if (!this.findText) return;
      this.editContent = this.editContent.replaceAll(this.findText, this.replaceText);
      this.updateFindCount();
    },
    async reloadActiveFile() {
      if (!this.activeFile || this.isImage || this.isPdf) return;
      try {
        const res = await filesFetch(this._filesUrl(this.activeFile.path));
        if (!res) return;
        if (!res.ok) return;
        const data = await res.json();
        this.activeFile.content = data.content;
      } catch (e) {
        // Silently skip reload failures
      }
    },
    getExt(name) {
      const dot = name.lastIndexOf('.');
      return dot >= 0 ? name.substring(dot).toLowerCase() : '';
    },
    escapeHtml(str) {
      return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
  }
};
