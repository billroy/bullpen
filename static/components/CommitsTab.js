const CommitsTab = {
  props: ['workspaceId', 'openDiffHash'],
  emits: ['handled-open-diff-hash'],
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
      gitStatus: null,
      statusLoading: false,
      statusError: null,
      selectedGitAction: '',
      gitActionLoading: false,
      showGitActionMenu: false,
      gitActions: [
        { id: 'init', label: 'git init', icon: 'folder-git-2' },
        { id: 'fetch', label: 'git fetch --prune', icon: 'download' },
        { id: 'pull', label: 'git pull', icon: 'arrow-down-to-line' },
        { id: 'push', label: 'git push', icon: 'arrow-up-from-line' },
        { id: 'branch', label: 'git branch --all --verbose', icon: 'git-branch' },
        { id: 'remote', label: 'git remote --verbose', icon: 'radio-tower' },
      ],
      actionResult: null,
      actionError: null,
    };
  },
  mounted() {
    document.addEventListener('click', this.closeGitActionMenu);
    renderLucideIcons(this.$el);
    this.refresh();
  },
  updated() {
    this.$nextTick(() => renderLucideIcons(this.$el));
  },
  beforeUnmount() {
    document.removeEventListener('click', this.closeGitActionMenu);
  },
  watch: {
    workspaceId(newId, oldId) {
      if (newId === oldId) return;
      this.closeDiff();
      this.refresh();
    },
    openDiffHash: {
      immediate: true,
      handler(newHash) {
        this.openDiffByHash(newHash);
      },
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
      this.refreshGitStatus();
      this.commits = [];
      this.offset = 0;
      this.hasMore = false;
      this.error = null;
      await this.loadMore();
      await this.loadUntilOlderThanToday();
    },
    async refreshGitStatus() {
      this.statusLoading = true;
      this.statusError = null;
      try {
        const data = await this.$root.requestGitStatus({
          workspaceId: this.workspaceId,
        });
        this.gitStatus = data;
      } catch (e) {
        this.gitStatus = null;
        this.statusError = e.message;
      } finally {
        this.statusLoading = false;
      }
    },
    _coerceCommitDate(dateStr) {
      if (!dateStr) return null;
      const parsed = new Date(dateStr);
      if (!Number.isNaN(parsed.getTime())) return parsed;
      // Fallback for git date strings if browser parsing is strict.
      const dateOnly = String(dateStr).trim().slice(0, 10);
      if (/^\d{4}-\d{2}-\d{2}$/.test(dateOnly)) {
        const fallback = new Date(`${dateOnly}T00:00:00`);
        if (!Number.isNaN(fallback.getTime())) return fallback;
      }
      return null;
    },
    _isTodayCommit(commit) {
      const parsed = this._coerceCommitDate(commit?.date);
      if (!parsed) return false;
      const now = new Date();
      return (
        parsed.getFullYear() === now.getFullYear() &&
        parsed.getMonth() === now.getMonth() &&
        parsed.getDate() === now.getDate()
      );
    },
    _lastLoadedCommitIsToday() {
      if (!this.commits.length) return false;
      return this._isTodayCommit(this.commits[this.commits.length - 1]);
    },
    async loadUntilOlderThanToday() {
      while (this.hasMore && this._lastLoadedCommitIsToday()) {
        const loaded = await this.loadMore();
        if (!loaded) break;
      }
    },
    async loadMore() {
      if (this.loading) return;
      this.loading = true;
      this.error = null;
      let loaded = 0;
      try {
        const data = await this.$root.requestCommits({
          workspaceId: this.workspaceId,
          offset: String(this.offset),
          count: '10',
        });
        if (data.error) {
          this.error = data.error;
          return;
        }
        this.commits.push(...data.commits);
        this.hasMore = data.has_more;
        loaded = data.commits.length;
        this.offset += loaded;
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
      return loaded;
    },
    formatDate(dateStr) {
      if (!dateStr) return '';
      try {
        return new Date(dateStr).toLocaleString();
      } catch (e) {
        return dateStr;
      }
    },
    commitOriginRefs(commit) {
      const refs = Array.isArray(commit?.refs) ? commit.refs : [];
      return refs.filter((ref) => {
        const text = String(ref || '').trim();
        return text.startsWith('origin/');
      });
    },
    async openDiff(commit) {
      this.selectedCommit = commit;
      this.commitDiff = '';
      this.diffError = null;
      this.diffLoading = true;
      this.$nextTick(() => this.$refs.diffOverlay?.focus());
      try {
        const data = await this.$root.requestCommitDiff({
          workspaceId: this.workspaceId,
          hash: commit.hash,
        });
        if (data.error) {
          this.diffError = data.error;
          return;
        }
        this.commitDiff = data.diff || '';
      } catch (e) {
        this.diffError = e.message;
      } finally {
        this.diffLoading = false;
      }
    },
    async openBranchDiff() {
      this.selectedCommit = {
        short_hash: 'Branch',
        subject: 'Current branch diff',
        author: '',
        date: '',
      };
      this.commitDiff = '';
      this.diffError = null;
      this.diffLoading = true;
      this.$nextTick(() => this.$refs.diffOverlay?.focus());
      try {
        const data = await this.$root.requestGitBranchDiff({
          workspaceId: this.workspaceId,
        });
        if (data.error) {
          this.diffError = data.error;
          return;
        }
        const branch = data.branch || 'current branch';
        const base = data.base || 'base';
        this.selectedCommit = {
          short_hash: branch,
          subject: `diff against ${base}`,
          author: '',
          date: '',
        };
        this.commitDiff = data.diff || 'No branch diff.';
      } catch (e) {
        this.diffError = e.message;
      } finally {
        this.diffLoading = false;
      }
    },
    toggleGitActionMenu() {
      if (this.gitActionLoading) return;
      this.showGitActionMenu = !this.showGitActionMenu;
    },
    closeGitActionMenu() {
      this.showGitActionMenu = false;
    },
    async runGitAction(action) {
      action = action || this.selectedGitAction;
      this.selectedGitAction = '';
      this.showGitActionMenu = false;
      if (!action || this.gitActionLoading) return;
      this.gitActionLoading = true;
      this.actionError = null;
      this.actionResult = null;
      try {
        const data = await this.$root.requestGitAction({
          workspaceId: this.workspaceId,
          action,
        });
        this.actionResult = data;
        if (data.error) this.actionError = data.error;
        await this.refreshGitStatus();
        if (['init', 'fetch', 'pull'].includes(action)) {
          await this.refresh();
        }
      } catch (e) {
        this.actionError = e.message;
      } finally {
        this.gitActionLoading = false;
      }
    },
    async openDiffByHash(hash) {
      const normalized = String(hash || '').trim();
      if (!normalized) return;
      if (!/^[0-9a-f]{7,40}$/i.test(normalized)) {
        this.$emit('handled-open-diff-hash', normalized);
        return;
      }
      const existing = this.commits.find((commit) => {
        const commitHash = String(commit?.hash || '').toLowerCase();
        const desired = normalized.toLowerCase();
        return commitHash === desired || commitHash.startsWith(desired);
      });
      const commit = existing || {
        hash: normalized,
        short_hash: normalized.slice(0, 7),
        subject: 'Commit',
        author: '',
        date: '',
      };
      await this.openDiff(commit);
      this.$emit('handled-open-diff-hash', normalized);
    },
    closeDiff() {
      this.selectedCommit = null;
      this.commitDiff = '';
      this.diffError = null;
      this.diffLoading = false;
    },
    closeActionResult() {
      this.actionResult = null;
      this.actionError = null;
    },
  },
  template: `
    <div class="commits-container">
      <div class="git-status-panel">
        <div class="git-status-main">
          <div class="git-status-title">
            <i data-lucide="git-branch" aria-hidden="true"></i>
            <span>{{ gitStatus?.branch || 'Git status' }}</span>
          </div>
          <div v-if="statusLoading" class="commits-loading">Loading status...</div>
          <div v-else-if="statusError" class="commits-error">{{ statusError }}</div>
          <div v-else-if="gitStatus" class="git-status-summary">
            <span :class="['git-status-pill', gitStatus.clean ? 'git-status-clean' : 'git-status-dirty']">
              {{ gitStatus.clean ? 'Clean working tree' : gitStatus.changes.length + ' changed file' + (gitStatus.changes.length === 1 ? '' : 's') }}
            </span>
          </div>
        </div>
        <div class="git-status-actions">
          <button class="btn btn-sm" @click="refresh" :disabled="loading || statusLoading">
            <i data-lucide="refresh-cw" aria-hidden="true"></i>
            Refresh
          </button>
          <button class="btn btn-sm" @click="openBranchDiff" :disabled="diffLoading">
            <i data-lucide="file-diff" aria-hidden="true"></i>
            Branch Diff
          </button>
          <div class="git-action-menu-wrap" @click.stop>
            <button
              class="btn btn-sm btn-icon git-action-menu-button"
              @click="toggleGitActionMenu"
              :disabled="gitActionLoading"
              :aria-expanded="showGitActionMenu ? 'true' : 'false'"
              aria-haspopup="menu"
              :title="gitActionLoading ? 'Running git command' : 'Git commands'"
              aria-label="Git commands"
            >
              <i data-lucide="menu" aria-hidden="true"></i>
            </button>
            <div v-if="showGitActionMenu" class="project-menu git-action-menu" role="menu">
              <button
                v-for="action in gitActions"
                :key="action.id"
                class="project-menu-item"
                type="button"
                role="menuitem"
                @click="runGitAction(action.id)"
              >
                <i class="menu-item-icon" :data-lucide="action.icon" aria-hidden="true"></i>
                <span class="menu-item-label">{{ action.label }}</span>
              </button>
            </div>
          </div>
        </div>
        <pre v-if="gitStatus?.changes?.length" class="git-status-changes">{{ gitStatus.changes.join('\\n') }}</pre>
      </div>
      <div class="commits-toolbar">
        <span class="commits-section-title">Recent commits</span>
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
          <span class="commit-ref-column">
            <span class="commit-hash">{{ commit.short_hash }}</span>
            <span
              v-for="ref in commitOriginRefs(commit)"
              :key="commit.hash + '-' + ref"
              class="commit-origin-pill"
              :title="'Remote ref ' + ref"
            >{{ ref }}</span>
          </span>
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
            <div v-if="selectedCommit.author || selectedCommit.date" class="commit-meta">{{ selectedCommit.author }} &middot; {{ formatDate(selectedCommit.date) }}</div>
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
      <div
        v-if="actionResult || actionError"
        class="modal-overlay commits-diff-overlay"
        @click.self="closeActionResult"
        @keydown.escape="closeActionResult"
        tabindex="0"
      >
        <div class="modal commits-diff-modal">
          <div class="modal-header">
            <h2>{{ actionResult?.command || 'Git command' }}</h2>
            <button class="btn btn-icon" @click="closeActionResult">&times;</button>
          </div>
          <div class="modal-body commits-diff-body">
            <div v-if="actionError" class="commits-error">{{ actionError }}</div>
            <pre class="commit-diff">{{ actionResult?.output || 'No output.' }}</pre>
          </div>
          <div class="modal-footer">
            <div></div>
            <button class="btn btn-primary" @click="closeActionResult">Close</button>
          </div>
        </div>
      </div>
    </div>
  `,
};
