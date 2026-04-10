const CommitsTab = {
  data() {
    return {
      commits: [],
      offset: 0,
      hasMore: false,
      loading: false,
      error: null,
    };
  },
  mounted() {
    this.refresh();
  },
  methods: {
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
        const res = await fetch(`/api/commits?offset=${this.offset}&count=10`);
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
  },
  template: `
    <div class="commits-container">
      <div class="commits-toolbar">
        <button class="btn btn-sm" @click="refresh" :disabled="loading">Refresh</button>
      </div>
      <div class="commits-list">
        <div v-if="error" class="commits-error">{{ error }}</div>
        <div v-else-if="commits.length === 0 && !loading" class="empty-state">No commits found.</div>
        <div v-for="commit in commits" :key="commit.hash" class="commit-row">
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
    </div>
  `,
};
