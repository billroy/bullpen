const { createApp, computed, onMounted, reactive, ref, watch } = Vue;

createApp({
  setup() {
    const state = reactive({
      profiles: [],
      selectedId: null,
      loading: false,
      error: '',
      logs: '',
      actionBusy: '',
      setupBusy: false,
      setupSessionId: '',
      setupProfileId: '',
      setupOutput: '',
      setupInput: '',
      setupExit: '',
    });
    const socketRef = ref(null);
    const setupInputRef = ref(null);

    const form = reactive({
      displayName: 'Local Bullpen',
      workspaceRoot: '',
      runtime: 'local',
      adminUser: 'admin',
      adminPassword: '',
      sandboxName: '',
      base: 'bullpen-microsandbox-local',
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

    function resetSetupState() {
      state.setupSessionId = '';
      state.setupProfileId = '';
      state.setupOutput = '';
      state.setupInput = '';
      state.setupExit = '';
    }

    function hasActiveSetupSession(profile) {
      return Boolean(
        profile
        && stateLabel(profile) === 'setup-running'
        && state.setupSessionId
        && state.setupProfileId === profile.id
        && !state.setupExit
      );
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
          await syncSetupSession(selected.value);
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
        form.adminUser = 'admin';
        form.adminPassword = '';
        form.sandboxName = '';
        form.base = 'bullpen-microsandbox-local';
        form.autoStartWhenManagerStarts = false;
        await refresh();
      } catch (err) {
        state.error = err.message;
      }
    }

    async function action(profile, name) {
      if (!profile) return;
      state.error = '';
      state.actionBusy = `${profile.id}:${name}`;
      try {
        await api(`/api/profiles/${profile.id}/${name}`, { method: 'POST', body: '{}' });
        await refresh();
      } catch (err) {
        state.error = err.message;
      } finally {
        state.actionBusy = '';
      }
    }

    async function deleteProfile(profile) {
      if (!profile) return;
      if (!confirm(`Delete profile "${profile.displayName}"? This will not delete the workspace.`)) return;
      state.error = '';
      try {
        await api(`/api/profiles/${profile.id}`, { method: 'DELETE' });
        state.selectedId = null;
        resetSetupState();
        await refresh();
      } catch (err) {
        state.error = err.message;
      }
    }

    async function setupProviders(profile) {
      if (!profile || profile.runtime !== 'microsandbox') return;
      state.error = '';
      state.setupBusy = true;
      state.setupSessionId = '';
      state.setupProfileId = profile.id;
      state.setupOutput = '';
      state.setupInput = '';
      state.setupExit = '';
      try {
        const data = await api(`/api/profiles/${profile.id}/setup-providers/start`, { method: 'POST', body: '{}' });
        state.setupSessionId = data.sessionId;
        state.setupProfileId = profile.id;
        if (data.profile) {
          const index = state.profiles.findIndex(item => item.id === data.profile.id);
          if (index >= 0) state.profiles[index] = data.profile;
        }
        const logData = await api(`/api/profiles/${profile.id}/logs`);
        state.setupOutput = logData.text || state.setupOutput;
      } catch (err) {
        state.error = err.message;
      } finally {
        state.setupBusy = false;
      }
    }

    async function syncSetupSession(profile) {
      if (!profile || profile.runtime !== 'microsandbox') return;
      if (stateLabel(profile) !== 'setup-running') {
        if (state.setupProfileId === profile.id) resetSetupState();
        return;
      }
      if (state.setupProfileId === profile.id && state.setupSessionId) return;
      try {
        const data = await api(`/api/profiles/${profile.id}/setup-providers/session`);
        state.setupSessionId = data.sessionId || '';
        state.setupProfileId = profile.id;
        state.setupExit = data.sessionId ? '' : 'Setup input channel unavailable';
        const logData = await api(`/api/profiles/${profile.id}/logs`);
        state.setupOutput = logData.text || state.setupOutput;
      } catch (err) {
        state.error = err.message;
      }
    }

    function sendSetupInput() {
      if (!state.setupSessionId || !socketRef.value) return;
      socketRef.value.emit('manager:pty-input', {
        sessionId: state.setupSessionId,
        data: `${state.setupInput}\n`,
      });
      state.setupInput = '';
    }

    function pasteIntoSetupInput(event) {
      if (!event || !event.clipboardData) return;
      const text = event.clipboardData.getData('text');
      if (!text) return;
      state.setupInput += text;
      setTimeout(() => {
        if (setupInputRef.value) setupInputRef.value.focus();
      }, 0);
    }

    function focusSetupInput() {
      if (setupInputRef.value && state.setupSessionId && !state.setupExit) {
        setupInputRef.value.focus();
      }
    }

    function setupStatusText(profile) {
      if (state.setupExit && state.setupProfileId === profile.id) return state.setupExit;
      if (hasActiveSetupSession(profile)) return 'Interactive session active';
      if (stateLabel(profile) === 'setup-running') return 'Reconnecting to setup session';
      return 'No setup session active';
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
      socketRef.value = socket;
      socket.on('manager:updated', (payload) => {
        state.profiles = payload.profiles || [];
        if (selected.value) {
          loadLogs(selected.value.id);
          syncSetupSession(selected.value);
        }
      });
      socket.on('manager:pty-output', (payload) => {
        if (!payload || payload.sessionId !== state.setupSessionId) return;
        state.setupOutput += payload.text || '';
      });
      socket.on('manager:pty-exit', (payload) => {
        if (!payload || payload.sessionId !== state.setupSessionId) return;
        state.setupExit = `Provider setup exited with ${payload.returncode}`;
        if (selected.value) loadLogs(selected.value.id);
      });
      socket.on('manager:error', (payload) => {
        state.error = (payload && payload.error) || 'Manager error';
      });
    });

    watch(selected, (profile) => {
      if (!profile) return;
      loadLogs(profile.id);
      syncSetupSession(profile);
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
      setupProviders,
      syncSetupSession,
      sendSetupInput,
      pasteIntoSetupInput,
      focusSetupInput,
      setupStatusText,
      hasActiveSetupSession,
      setupInputRef,
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
                  <option value="microsandbox">Microsandbox</option>
                  <option value="docker" disabled>Docker (later)</option>
                </select>
              </div>
              <div class="field">
                <label>Workspace Root</label>
                <input v-model="form.workspaceRoot" placeholder="/Users/bill/aistuff" required>
              </div>
              <template v-if="form.runtime === 'microsandbox'">
                <div class="field">
                  <label>Sandbox Name</label>
                  <input v-model="form.sandboxName" placeholder="bullpen-personal">
                </div>
                <div class="field">
                  <label>Base Snapshot</label>
                  <input v-model="form.base">
                </div>
                <div class="field">
                  <label>Admin User</label>
                  <input v-model="form.adminUser">
                </div>
                <div class="field">
                  <label>Admin Password</label>
                  <input type="password" v-model="form.adminPassword" required>
                </div>
              </template>
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
              @click="state.selectedId = profile.id; loadLogs(profile.id); syncSetupSession(profile)"
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
                  <button class="primary" @click="action(selected, 'start')" :disabled="state.actionBusy === selected.id + ':start'">
                    {{ state.actionBusy === selected.id + ':start' ? 'Starting...' : 'Start' }}
                  </button>
                  <button @click="action(selected, 'stop')" :disabled="state.actionBusy === selected.id + ':stop'">Stop</button>
                  <button @click="action(selected, 'restart')" :disabled="state.actionBusy === selected.id + ':restart'">Restart</button>
                  <button @click="openInstance(selected)">Open</button>
                  <button
                    v-if="selected.runtime === 'microsandbox'"
                    @click="setupProviders(selected)"
                    :disabled="state.setupBusy || hasActiveSetupSession(selected)"
                  >
                    {{ state.setupBusy || hasActiveSetupSession(selected) ? 'Setting Up...' : 'Setup Providers' }}
                  </button>
                  <button class="danger" @click="deleteProfile(selected)">Delete</button>
                </div>
                <div class="kv"><strong>URL</strong><span>{{ urlFor(selected) }}</span></div>
                <div class="kv"><strong>Workspace</strong><span>{{ selected.workspaceRoot }}</span></div>
                <div class="kv"><strong>Home</strong><span>{{ selected.instanceHome }}</span></div>
                <div class="kv" v-if="selected.sandboxName"><strong>Sandbox</strong><span>{{ selected.sandboxName }}</span></div>
                <div class="kv" v-if="selected.base"><strong>Base</strong><span>{{ selected.base }}</span></div>
                <div class="kv"><strong>Ports</strong><span>{{ portText(selected) }}</span></div>
                <div class="kv" v-if="selected.observed && selected.observed.pid"><strong>PID</strong><span>{{ selected.observed.pid }}</span></div>
                <div class="kv" v-if="selected.observed && selected.observed.lastError"><strong>Error</strong><span>{{ selected.observed.lastError }}</span></div>
              </div>
            </div>

            <div class="panel" v-if="selected.runtime === 'microsandbox'">
              <div class="panel-header">
                <div>
                  <div class="panel-title">Provider Setup</div>
                  <div class="instance-meta">{{ setupStatusText(selected) }}</div>
                </div>
              </div>
              <div class="terminal-panel">
                <pre
                  class="log-box terminal-box"
                  tabindex="0"
                  @click="focusSetupInput"
                  @paste.prevent="pasteIntoSetupInput"
                >{{ state.setupOutput || 'Press Setup Providers to run Claude, Codex, and Git setup in an interactive sandbox terminal.' }}</pre>
                <form class="terminal-input" @submit.prevent="sendSetupInput">
                  <textarea
                    ref="setupInputRef"
                    v-model="state.setupInput"
                    :disabled="!state.setupSessionId || !!state.setupExit"
                    placeholder="Paste code or type a response"
                    rows="2"
                    @keydown.enter.exact.prevent="sendSetupInput"
                  ></textarea>
                  <button type="submit" :disabled="!state.setupSessionId || !!state.setupExit">Send</button>
                </form>
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
            Create a Bullpen instance to get started.
          </div>
        </main>
      </div>
    </div>
  `,
}).mount('#app');
