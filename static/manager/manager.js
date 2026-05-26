const { createApp, computed, onMounted, reactive, ref } = Vue;

createApp({
  setup() {
    const state = reactive({
      profiles: [],
      selectedId: null,
      loading: false,
      error: '',
      logs: '',
    });

    const form = reactive({
      displayName: 'Local Bullpen',
      workspaceRoot: '',
      runtime: 'local',
      autoStartWhenManagerStarts: false,
    });

    const selected = computed(() => state.profiles.find(profile => profile.id === state.selectedId) || state.profiles[0] || null);

    function stateLabel(profile) {
      return (profile && profile.observed && profile.observed.state) || 'unknown';
    }

    function portText(profile) {
      if (!profile || !profile.ports) return '';
      return `Bullpen ${profile.ports.bullpen} / App ${profile.ports.app}`;
    }

    function urlFor(profile) {
      if (!profile || !profile.ports) return '';
      return `http://127.0.0.1:${profile.ports.bullpen}`;
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || `Request failed: ${response.status}`);
      }
      return data;
    }

    async function refresh() {
      state.loading = true;
      state.error = '';
      try {
        const data = await api('/api/profiles');
        state.profiles = data.profiles || [];
        if (!state.selectedId && state.profiles.length) {
          state.selectedId = state.profiles[0].id;
        }
        if (selected.value) {
          await loadLogs(selected.value.id);
        }
      } catch (err) {
        state.error = err.message;
      } finally {
        state.loading = false;
      }
    }

    async function createProfile() {
      state.error = '';
      try {
        const data = await api('/api/profiles', {
          method: 'POST',
          body: JSON.stringify(form),
        });
        state.selectedId = data.profile.id;
        form.displayName = 'Local Bullpen';
        form.workspaceRoot = '';
        form.autoStartWhenManagerStarts = false;
        await refresh();
      } catch (err) {
        state.error = err.message;
      }
    }

    async function action(profile, name) {
      if (!profile) return;
      state.error = '';
      try {
        await api(`/api/profiles/${profile.id}/${name}`, { method: 'POST', body: '{}' });
        await refresh();
      } catch (err) {
        state.error = err.message;
      }
    }

    async function deleteProfile(profile) {
      if (!profile) return;
      if (!confirm(`Delete profile "${profile.displayName}"? This will not delete the workspace.`)) return;
      state.error = '';
      try {
        await api(`/api/profiles/${profile.id}`, { method: 'DELETE' });
        state.selectedId = null;
        await refresh();
      } catch (err) {
        state.error = err.message;
      }
    }

    async function loadLogs(profileId) {
      try {
        const data = await api(`/api/profiles/${profileId}/logs`);
        state.logs = data.text || '';
      } catch (_err) {
        state.logs = '';
      }
    }

    function openInstance(profile) {
      if (!profile) return;
      window.open(urlFor(profile), '_blank', 'noopener');
    }

    onMounted(() => {
      refresh();
      const socket = io();
      socket.on('manager:updated', (payload) => {
        state.profiles = payload.profiles || [];
        if (selected.value) loadLogs(selected.value.id);
      });
    });

    return {
      state,
      form,
      selected,
      stateLabel,
      portText,
      urlFor,
      refresh,
      createProfile,
      action,
      deleteProfile,
      loadLogs,
      openInstance,
    };
  },
  template: `
    <div class="manager-shell">
      <header class="topbar">
        <div class="brand">
          <div class="brand-title">Bullpen Manager</div>
          <div class="brand-subtitle">Local control plane for Bullpen instances</div>
        </div>
        <button @click="refresh" :disabled="state.loading">Refresh</button>
      </header>

      <div class="content">
        <aside class="sidebar">
          <section class="panel">
            <div class="panel-header">
              <div class="panel-title">Create Instance</div>
            </div>
            <form class="create-form" @submit.prevent="createProfile">
              <div class="field">
                <label>Name</label>
                <input v-model="form.displayName" required>
              </div>
              <div class="field">
                <label>Runtime</label>
                <select v-model="form.runtime">
                  <option value="local">Local</option>
                  <option value="microsandbox" disabled>Microsandbox (later)</option>
                  <option value="docker" disabled>Docker (later)</option>
                </select>
              </div>
              <div class="field">
                <label>Workspace Root</label>
                <input v-model="form.workspaceRoot" placeholder="/Users/bill/aistuff" required>
              </div>
              <label class="status-line">
                <input type="checkbox" v-model="form.autoStartWhenManagerStarts" style="width:auto">
                Auto-start when manager starts
              </label>
              <button class="primary" type="submit">Create</button>
            </form>
          </section>

          <div class="instance-list">
            <button
              v-for="profile in state.profiles"
              :key="profile.id"
              class="instance-row"
              :class="{ active: selected && selected.id === profile.id }"
              @click="state.selectedId = profile.id; loadLogs(profile.id)"
            >
              <span class="instance-name">{{ profile.displayName }}</span>
              <span class="instance-meta">{{ profile.runtime }} / {{ portText(profile) }}</span>
              <span class="status-line"><span class="dot" :class="stateLabel(profile)"></span>{{ stateLabel(profile) }}</span>
            </button>
          </div>
        </aside>

        <main class="main">
          <div v-if="state.error" class="error">{{ state.error }}</div>

          <section v-if="selected" class="detail">
            <div class="panel">
              <div class="panel-header">
                <div>
                  <div class="panel-title">{{ selected.displayName }}</div>
                  <div class="instance-meta">{{ selected.id }} / {{ selected.runtime }}</div>
                </div>
                <div class="status-line"><span class="dot" :class="stateLabel(selected)"></span>{{ stateLabel(selected) }}</div>
              </div>
              <div class="create-form">
                <div class="actions">
                  <button class="primary" @click="action(selected, 'start')">Start</button>
                  <button @click="action(selected, 'stop')">Stop</button>
                  <button @click="action(selected, 'restart')">Restart</button>
                  <button @click="openInstance(selected)">Open</button>
                  <button class="danger" @click="deleteProfile(selected)">Delete</button>
                </div>
                <div class="kv"><strong>URL</strong><span>{{ urlFor(selected) }}</span></div>
                <div class="kv"><strong>Workspace</strong><span>{{ selected.workspaceRoot }}</span></div>
                <div class="kv"><strong>Home</strong><span>{{ selected.instanceHome }}</span></div>
                <div class="kv"><strong>Ports</strong><span>{{ portText(selected) }}</span></div>
                <div class="kv" v-if="selected.observed && selected.observed.pid"><strong>PID</strong><span>{{ selected.observed.pid }}</span></div>
                <div class="kv" v-if="selected.observed && selected.observed.lastError"><strong>Error</strong><span>{{ selected.observed.lastError }}</span></div>
              </div>
            </div>

            <div class="panel">
              <div class="panel-header">
                <div class="panel-title">Logs</div>
                <button @click="loadLogs(selected.id)">Reload Logs</button>
              </div>
              <pre class="log-box">{{ state.logs || 'No logs yet.' }}</pre>
            </div>
          </section>

          <div v-else class="empty">
            Create a local Bullpen instance to get started.
          </div>
        </main>
      </div>
    </div>
  `,
}).mount('#app');
