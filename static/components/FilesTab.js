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
            @click="activeFile = f"
          >
            <span class="file-tab-name">{{ f.name }}</span>
            <button class="file-tab-close" @click.stop="closeFile(f.path)">&times;</button>
          </div>
        </div>
        <div class="files-viewer-body" v-if="activeFile">
          <!-- Image -->
          <div v-if="isImage" class="file-view-image">
            <img :src="'/api/files/' + activeFile.path" :alt="activeFile.name" />
          </div>
          <!-- PDF -->
          <div v-else-if="isPdf" class="file-view-pdf">
            <embed :src="'/api/files/' + activeFile.path" type="application/pdf" width="100%" height="100%" />
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
            <pre v-else class="file-source"><code>{{ activeFile.content }}</code></pre>
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
    }
  },
  mounted() {
    this.loadTree();
  },
  methods: {
    async loadTree() {
      try {
        const res = await fetch('/api/files');
        this.tree = await res.json();
      } catch (e) {
        console.error('Failed to load file tree', e);
      }
    },
    async openFile(node) {
      if (node.type !== 'file') return;
      const existing = this.openFiles.find(f => f.path === node.path);
      if (existing) {
        this.activeFile = existing;
        return;
      }
      // Images/PDFs don't need content fetch
      const ext = this.getExt(node.name);
      if (['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.bmp', '.pdf'].includes(ext)) {
        const file = { path: node.path, name: node.name, content: null };
        this.openFiles.push(file);
        this.activeFile = file;
        return;
      }
      try {
        const res = await fetch('/api/files/' + encodeURI(node.path));
        if (!res.ok) throw new Error('Failed to load');
        const data = await res.json();
        const file = { path: node.path, name: node.name, content: data.content };
        this.openFiles.push(file);
        this.activeFile = file;
      } catch (e) {
        console.error('Failed to open file', e);
      }
    },
    closeFile(path) {
      const idx = this.openFiles.findIndex(f => f.path === path);
      if (idx < 0) return;
      this.openFiles.splice(idx, 1);
      if (this.activeFile?.path === path) {
        this.activeFile = this.openFiles[Math.min(idx, this.openFiles.length - 1)] || null;
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
