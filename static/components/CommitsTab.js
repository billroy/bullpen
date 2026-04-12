const CommitsTab = {
  props: ['workspaceId'],
  computed: {
    highlightedDiffHtml() {
      return this.renderDiffHtml(this.commitDiff || 'No diff output.');
    },
  },
  data() {
    return {
      commits: [],
      offset: 0,
      hasMore: false,
      loading: false,
      error: null,
      selectedCommit: null,
      commitDiff: '',
      diffLoading: false,
      diffError: null,
    };
  },
  mounted() {
    this.refresh();
  },
  watch: {
    workspaceId(newId, oldId) {
      if (newId === oldId) return;
      this.closeDiff();
      this.refresh();
    },
  },
  methods: {
    escapeHtml(text) {
      return (text || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;');
    },
    classifyDiffLine(line) {
      if (line.startsWith('@@')) return 'commit-diff-line-hunk';
      if (line.startsWith('diff --git')) return 'commit-diff-line-meta';
      if (line.startsWith('index ')) return 'commit-diff-line-meta';
      if (line.startsWith('--- ')) return 'commit-diff-line-file-old';
      if (line.startsWith('+++ ')) return 'commit-diff-line-file-new';
      if (line.startsWith('+')) return 'commit-diff-line-add';
      if (line.startsWith('-')) return 'commit-diff-line-remove';
      return '';
    },
    renderDiffHtml(text) {
      return text
        .split('\n')
        .map((line) => {
          const lineClass = this.classifyDiffLine(line);
          const className = lineClass ? `commit-diff-line ${lineClass}` : 'commit-diff-line';
          const content = this.escapeHtml(line);
          return `<span class="${className}">${content}</span>`;
        })
        .join('');
    },
    async refresh() {
      this.commits = [];
      this.offset = 0;
      this.hasMore = false;
      this.error = null;
      await this.loadMore();
    },
    async loadMore() {
      if (this.loading) return;
      this.loading = true;
      this.error = null;
      try {
        const params = new URLSearchParams({
          offset: String(this.offset),
          count: '10',
        });
        if (this.workspaceId) params.set('workspaceId', this.workspaceId);
        const res = await fetch(`/api/commits?${params.toString()}`);
        if (res.status === 401) {
          window.location = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
          return;
        }
        const data = await res.json();
        if (data.error) {
          this.error = data.error;
          return;
        }
        this.commits.push(...data.commits);
        this.hasMore = data.has_more;
        this.offset += data.commits.length;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },
    formatDate(dateStr) {
      if (!dateStr) return '';
      try {
        return new Date(dateStr).toLocaleString();
      } catch (e) {
        return dateStr;
      }
    },
    async openDiff(commit) {
      this.selectedCommit = commit;
      this.commitDiff = '';
      this.diffError = null;
      this.diffLoading = true;
      this.$nextTick(() => this.$refs.diffOverlay?.focus());
      try {
        const params = new URLSearchParams();
        if (this.workspaceId) params.set('workspaceId', this.workspaceId);
        const query = params.toString();
        const diffUrl = `/api/commits/${encodeURIComponent(commit.hash)}/diff${query ? `?${query}` : ''}`;
        const res = await fetch(diffUrl);
        if (res.status === 401) {
          window.location = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
          return;
        }
        const data = await res.json();
        if (!res.ok || data.error) {
          this.diffError = data.error || `Failed to load diff (${res.status})`;
          return;
        }
        this.commitDiff = data.diff || '';
      } catch (e) {
        this.diffError = e.message;
      } finally {
        this.diffLoading = false;
      }
    },
    closeDiff() {
      this.selectedCommit = null;
      this.commitDiff = '';
      this.diffError = null;
      this.diffLoading = false;
    },
  },
  template: `
    <div class="commits-container">
      <div class="commits-toolbar">
        <button class="btn btn-sm" @click="refresh" :disabled="loading">Refresh</button>
      </div>
      <div class="commits-list">
        <div v-if="error" class="commits-error">{{ error }}</div>
        <div v-else-if="commits.length === 0 && !loading" class="empty-state">No commits found.</div>
        <div
          v-for="commit in commits"
          :key="commit.hash"
          class="commit-row commit-row-clickable"
          @click="openDiff(commit)"
          @keydown.enter.prevent="openDiff(commit)"
          tabindex="0"
          role="button"
          :title="'View diff for ' + commit.short_hash"
        >
          <span class="commit-hash">{{ commit.short_hash }}</span>
          <span class="commit-multiline">
            <span class="commit-subject">{{ commit.subject }}</span>
            <span class="commit-meta">{{ commit.author }} &middot; {{ formatDate(commit.date) }}</span>
            <span v-if="commit.body" class="commit-body">{{ commit.body }}</span>
          </span>
        </div>
      </div>
      <div class="commits-footer">
        <button v-if="hasMore" class="btn btn-sm" @click="loadMore" :disabled="loading">
          {{ loading ? 'Loading...' : 'More' }}
        </button>
        <span v-if="loading" class="commits-loading">Loading...</span>
      </div>
      <div
        v-if="selectedCommit"
        class="modal-overlay commits-diff-overlay"
        @click.self="closeDiff"
        @keydown.escape="closeDiff"
        tabindex="0"
        ref="diffOverlay"
      >
        <div class="modal commits-diff-modal">
          <div class="modal-header">
            <h2>{{ selectedCommit.short_hash }}: {{ selectedCommit.subject }}</h2>
            <button class="btn btn-icon" @click="closeDiff">&times;</button>
          </div>
          <div class="modal-body commits-diff-body">
            <div class="commit-meta">{{ selectedCommit.author }} &middot; {{ formatDate(selectedCommit.date) }}</div>
            <div v-if="diffLoading" class="commits-loading">Loading diff...</div>
            <div v-else-if="diffError" class="commits-error">{{ diffError }}</div>
            <pre v-else class="commit-diff" v-html="highlightedDiffHtml"></pre>
          </div>
          <div class="modal-footer">
            <div></div>
            <button class="btn btn-primary" @click="closeDiff">Close</button>
          </div>
        </div>
      </div>
    </div>
  `,
};
