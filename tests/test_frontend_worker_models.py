"""Regression checks for worker model options shown in the UI."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_codex_model_options_use_current_cli_catalog_as_fallback():
    text = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "codex: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'" in text
    assert "'gpt-5.6'" not in text
    assert "'gpt-5.5'" in text
    assert "'gpt-5.4'" in text
    assert "'gpt-5.4-mini'" in text
    assert "'gpt-5.2'" in text


def test_codex_uses_catalog_backed_model_picker():
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    modal = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text(encoding="utf-8")
    chat = (ROOT / "static" / "components" / "LiveAgentChatTab.js").read_text(encoding="utf-8")

    assert "function requestCodexModels(payload = {})" in app
    assert "socket.emit('models:codex', _wsData({ ...payload, request_id: requestId }));" in app
    assert "this.$root.requestCodexModels({" in modal
    assert "this.$root.requestCodexModels({" in chat
    assert "refreshCodexModels" in modal
    assert "refreshCodexModels" in chat
    assert "this.codexModels.map(model => model.id)" in modal
    assert "this.codexModels.map(model => model.id)" in chat
    assert "Enter model slug" in modal


def test_claude_model_options_are_fallback_only_and_exclude_stale_slugs():
    text = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "'claude-opus-4-8'" in text
    assert "'claude-opus-4-7'" in text
    assert "'claude-sonnet-5'" in text
    assert "'claude-fable-5'" in text
    assert "'claude-haiku-4-6'" not in text
    assert "'claude-haiku-4-5-20250414'" not in text
    assert "'claude-opus-4-5-20250514'" not in text
    assert "'claude-sonnet-4-5-20250514'" not in text
    assert "'claude-haiku-4-5'" in text


def test_claude_uses_models_dev_catalog_backed_picker():
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    modal = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text(encoding="utf-8")
    chat = (ROOT / "static" / "components" / "LiveAgentChatTab.js").read_text(encoding="utf-8")

    assert "function requestClaudeModels(payload = {})" in app
    assert "socket.emit('models:claude', _wsData({ ...payload, request_id: requestId }));" in app
    assert "this.$root.requestClaudeModels({" in modal
    assert "this.$root.requestClaudeModels({" in chat
    assert "refreshClaudeModels" in modal
    assert "refreshClaudeModels" in chat
    assert "this.claudeModels.map(model => model.id)" in modal
    assert "this.claudeModels.map(model => model.id)" in chat


def test_antigravity_model_options_present_and_gemini_provider_absent():
    text = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "antigravity:" in text
    assert "'Gemini 3.5 Flash (Medium)'" in text
    assert "'Claude Sonnet 4.6 (Thinking)'" in text
    assert "'GPT-OSS 120B (Medium)'" in text
    assert "gemini:" not in text
    assert "'gemini-2.5-flash'" not in text
    assert "'gemini-2.5-flash-lite'" not in text
    assert "'gemini-2.5-pro'" not in text
    assert "'gemini-3-pro-preview'" not in text
    assert "'pro'" not in text
    assert "'auto-gemini-2.5'" not in text
    assert "'gemini-2.0-flash'" not in text


def test_opencode_uses_catalog_backed_model_picker():
    utils = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    modal = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "opencode: []" in utils
    assert "agentOptions()" in modal
    assert "agentLabel(agent)" in modal
    assert "isOpenCodeAgent()" in modal
    assert "this.$root.requestOpenCodeModels({" in modal
    assert "/api/models/opencode" not in modal
    assert "function requestOpenCodeModels(payload = {})" in app
    assert "socket.emit('models:opencode', _wsData({ ...payload, request_id: requestId }));" in app
    assert "opencodeModelProvider" in modal
    assert "filteredOpenCodeModels" in modal
    assert "refreshOpenCodeModels" in modal
    assert 'placeholder="provider/model"' in modal
    assert "BULLPEN_OPENCODE_PATH" in modal
    assert ':active-workspace-id="activeWorkspaceId"' in app
    assert ':last-ai-selection="globalSettings.last_ai_selection"' in app


def test_live_agent_chat_exposes_opencode_catalog_picker():
    text = (ROOT / "static" / "components" / "LiveAgentChatTab.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

    assert "AI_PROVIDER_OPTIONS" in text
    assert "withPreferredOption" in text
    assert "isOpenCodeProvider()" in text
    assert "this.$root.requestOpenCodeModels({" in text
    assert "/api/models/opencode" not in text
    assert "opencodeModelProvider" in text
    assert "filteredOpenCodeModels" in text
    assert "refreshOpenCodeModels" in text
    assert 'placeholder="provider/model"' in text
    assert "BULLPEN_OPENCODE_PATH" in text
    assert "chat-model-select" in css


def test_model_options_defined_in_shared_constant():
    """Both components must use MODEL_OPTIONS from utils.js, not inline lists."""
    utils = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    assert "MODEL_OPTIONS" in utils

    for component in ("WorkerConfigModal.js", "LiveAgentChatTab.js"):
        text = (ROOT / "static" / "components" / component).read_text(encoding="utf-8")
        assert "MODEL_OPTIONS[" in text, f"{component} should reference MODEL_OPTIONS"
        # Should not have inline model arrays
        assert "codex-mini-latest" not in text, f"{component} has stale inline codex models"
        assert "o4-mini" not in text, f"{component} has stale inline codex models"


def test_last_ai_selection_promotes_provider_and_model_options():
    utils = (ROOT / "static" / "utils.js").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    modal = (ROOT / "static" / "components" / "WorkerConfigModal.js").read_text(encoding="utf-8")
    chat = (ROOT / "static" / "components" / "LiveAgentChatTab.js").read_text(encoding="utf-8")

    assert "function normalizedLastAiSelection" in utils
    assert "function withPreferredOption" in utils
    assert "socket.on('global:settings'" in app
    assert "lastAiSelection" in modal
    assert "withPreferredOption(AI_PROVIDER_OPTIONS" in modal
    assert "preferred?.agent === this.form.agent ? preferred.model" in modal
    assert "lastAiSelection" in chat
    assert "withPreferredOption(AI_PROVIDER_OPTIONS" in chat
    assert "preferred?.agent === this.provider ? preferred.model" in chat


def test_opencode_worker_catalog_refresh_keeps_all_providers_and_existing_results():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")

    script = r"""
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = process.cwd();
const source = fs.readFileSync(path.join(root, 'static/components/WorkerConfigModal.js'), 'utf8');
const context = {
  console,
  URLSearchParams,
  AI_PROVIDER_OPTIONS: ['claude', 'opencode'],
  MODEL_OPTIONS: { claude: ['claude-sonnet-4-6'], opencode: [] },
  normalizedLastAiSelection: () => null,
  withPreferredOption: (options) => options,
  setTimeout,
  clearTimeout,
  requestAnimationFrame: (fn) => fn(),
  document: {
    createElement: () => ({ style: {}, addEventListener() {}, removeEventListener() {}, setAttribute() {}, focus() {}, click() {} }),
    body: { appendChild() {} },
    documentElement: { clientWidth: 1280, clientHeight: 720 },
  },
  window: { innerWidth: 1280, innerHeight: 720, addEventListener() {}, removeEventListener() {} },
};

vm.createContext(context);
vm.runInContext(`${source}\n;globalThis.__WorkerConfigModal = WorkerConfigModal;`, context);
const component = context.__WorkerConfigModal;
let requests = [];

function makeInstance() {
  const instance = {
    ...component.data.call({}),
    form: { type: 'ai', agent: 'opencode', model: 'opencode/north-mini-code-free' },
    activeWorkspaceId: 'ws-test',
    $root: {
      activeWorkspaceId: 'ws-test',
      requestOpenCodeModels: async (payload) => {
        requests.push(payload);
        return {
          status: 'ok',
          models: [
            { id: 'opencode/north-mini-code-free', provider: 'opencode', model: 'north-mini-code-free' },
            { id: 'anthropic/claude-sonnet-4-6', provider: 'anthropic', model: 'claude-sonnet-4-6' },
          ],
        };
      },
    },
    $refs: {},
    $nextTick(fn) { if (typeof fn === 'function') fn(); },
  };
  for (const [name, getter] of Object.entries(component.computed || {})) {
    Object.defineProperty(instance, name, { get: () => getter.call(instance) });
  }
  for (const [name, method] of Object.entries(component.methods || {})) {
    instance[name] = method.bind(instance);
  }
  return instance;
}

(async () => {
  const instance = makeInstance();
  instance.syncOpenCodeModelProvider();
  assert.strictEqual(instance.opencodeModelProvider, '', 'saved model provider should not become an implicit filter');

  requests = [];

  await instance.refreshOpenCodeModels();
  assert.strictEqual(JSON.stringify(requests[0]), JSON.stringify({ workspaceId: 'ws-test', refresh: true }));
  assert.deepStrictEqual(instance.filteredOpenCodeModels.map((model) => model.id), [
    'opencode/north-mini-code-free',
    'anthropic/claude-sonnet-4-6',
  ]);

  instance.$root.requestOpenCodeModels = async () => ({ status: 'error', error: 'OpenCode model catalog timed out after 20s', models: [] });
  await instance.refreshOpenCodeModels();
  assert.deepStrictEqual(instance.opencodeModels.map((model) => model.id), [
    'opencode/north-mini-code-free',
    'anthropic/claude-sonnet-4-6',
  ]);
  assert.match(instance.opencodeModelsError, /timed out/);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""

    result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_dynamic_chat_catalogs_preserve_selection_without_overriding_catalog_order():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")

    script = r"""
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(process.cwd(), 'static/components/LiveAgentChatTab.js'), 'utf8');
const context = {
  console,
  crypto: { randomUUID: () => 'test' },
  AI_PROVIDER_OPTIONS: ['claude', 'codex'],
  MODEL_OPTIONS: { claude: ['claude-sonnet-4-6'], codex: ['gpt-fallback'] },
  normalizedLastAiSelection: () => null,
  withPreferredOption: (options, preferred) => preferred
    ? [preferred, ...options.filter((value) => value !== preferred)]
    : options.slice(),
  window: { _bullpenSocket: null },
};

vm.createContext(context);
vm.runInContext(`${source}\n;globalThis.__LiveAgentChatTab = LiveAgentChatTab;`, context);
const component = context.__LiveAgentChatTab;
const requests = [];
const instance = {
  ...component.data.call({ sessionId: null }),
  provider: 'codex',
  model: 'gpt-fallback',
  workspaceId: 'ws-test',
  lastAiSelection: null,
  $root: {
    requestCodexModels: async (payload) => {
      requests.push(payload);
      return {
        status: 'ok',
        models: [{ id: 'gpt-new' }, { id: 'gpt-fallback' }],
      };
    },
    requestClaudeModels: async (payload) => {
      requests.push(payload);
      return {
        status: 'ok',
        models: [{ id: 'claude-sonnet-5' }, { id: 'claude-opus-4-8' }],
      };
    },
  },
  $nextTick() {},
};
for (const [name, getter] of Object.entries(component.computed || {})) {
  Object.defineProperty(instance, name, { get: () => getter.call(instance) });
}
for (const [name, method] of Object.entries(component.methods || {})) {
  instance[name] = method.bind(instance);
}

(async () => {
  await instance.refreshCodexModels();
  assert.strictEqual(JSON.stringify(requests[0]), JSON.stringify({ workspaceId: 'ws-test', refresh: true }));
  assert.strictEqual(JSON.stringify(instance.modelOptions), JSON.stringify(['gpt-new', 'gpt-fallback']));
  assert.strictEqual(instance.model, 'gpt-fallback');

  instance.model = 'gpt-private-preview';
  assert.strictEqual(JSON.stringify(instance.modelOptions), JSON.stringify(['gpt-private-preview', 'gpt-new', 'gpt-fallback']));

  instance.provider = 'claude';
  instance.model = 'claude-private-preview';
  await instance.refreshClaudeModels();
  assert.strictEqual(JSON.stringify(requests[1]), JSON.stringify({ workspaceId: 'ws-test', refresh: true }));
  assert.strictEqual(JSON.stringify(instance.modelOptions), JSON.stringify(['claude-private-preview', 'claude-sonnet-5', 'claude-opus-4-8']));
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""

    result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
