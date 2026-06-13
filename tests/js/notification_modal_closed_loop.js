const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..');
const source = fs.readFileSync(path.join(root, 'static/components/WorkerConfigModal.js'), 'utf8');

const context = {
  console,
  setTimeout,
  clearTimeout,
  requestAnimationFrame: (fn) => fn(),
  MODEL_OPTIONS: { claude: ['claude-sonnet-4-6'] },
  document: {
    createElement: () => ({
      style: {},
      addEventListener() {},
      removeEventListener() {},
      setAttribute() {},
      focus() {},
      click() {},
    }),
    body: { appendChild() {} },
    documentElement: { clientWidth: 1280, clientHeight: 720 },
  },
  window: {
    innerWidth: 1280,
    innerHeight: 720,
    addEventListener() {},
    removeEventListener() {},
  },
};

vm.createContext(context);
vm.runInContext(`${source}\n;globalThis.__WorkerConfigModal = WorkerConfigModal;`, context);

const component = context.__WorkerConfigModal;

function makeInstance(worker) {
  const emitted = [];
  const instance = {
    worker,
    slotIndex: 0,
    columns: [
      { key: 'inbox', label: 'Inbox' },
      { key: 'review', label: 'Review' },
      { key: 'done', label: 'Done' },
    ],
    workers: [worker],
    gridRows: 4,
    gridCols: 4,
    providerColors: { notification: '#d7ad4a' },
    defaultProviderColors: { notification: '#d7ad4a' },
    activeWorkspaceId: 'ws-test',
    emitted,
    form: {},
    overlayMouseDown: false,
    servicePreview: null,
    servicePreviewError: '',
    servicePreviewLoading: false,
    serviceSuggestedPort: null,
    servicePortAutoFilled: false,
    servicePreviewSeq: 0,
    servicePreviewTimer: null,
    workerColorPickerInput: null,
    opencodeModels: [],
    opencodeModelsStatus: '',
    opencodeModelsError: '',
    opencodeModelsLoading: false,
    opencodeModelProvider: '',
    opencodeModelSearch: '',
    $refs: {},
    $root: { activeWorkspaceId: 'ws-test' },
    $nextTick(fn) { if (typeof fn === 'function') fn(); },
    $emit(name, payload) { emitted.push({ name, payload }); },
  };

  for (const [name, getter] of Object.entries(component.computed || {})) {
    Object.defineProperty(instance, name, { get: () => getter.call(instance) });
  }
  for (const [name, method] of Object.entries(component.methods || {})) {
    instance[name] = method.bind(instance);
  }
  component.watch.worker.handler.call(instance, worker, null);
  return instance;
}

const worker = {
  type: 'notification',
  name: 'Notification worker',
  activation: 'on_drop',
  disposition: 'review',
  paused: false,
  color: 'notification',
  notification: {},
};

const instance = makeInstance(worker);

instance.form.name = 'Escalation Bell';
instance.form.activation = 'on_interval';
instance.form.watch_column = 'review';
instance.form.trigger_time = '09:30';
instance.form.trigger_every_day = true;
instance.form.trigger_interval_minutes = 15;
instance.form.paused = false;
instance.form.disposition = 'random:';
instance.form.random_name = 'qa-router';
instance.form.color = '#123456';

instance.form.notification.toast.enabled = false;
instance.form.notification.toast.template = '{ticket.title} toast {worker.name} {workspace.name}';
instance.form.notification.toast.variant = 'warning';
instance.form.notification.toast.duration_ms = 12345;

instance.form.notification.speech.enabled = true;
instance.form.notification.speech.template = 'Speak {ticket.priority} {ticket.title}';
instance.form.notification.speech.engine = 'web-speech';
instance.form.notification.speech.voice = 'Samantha';
instance.form.notification.speech.rate = 1.4;
instance.form.notification.speech.volume = 0.6;

instance.form.notification.sound.enabled = true;
instance.form.notification.sound.effect = 'warning';
instance.form.notification.sound.repeat_count = 4;
instance.form.notification.sound.gap_ms = 750;
instance.form.notification.sound.volume = 0.7;

instance.form.notification.flash.enabled = true;
instance.addFlashStep();
instance.form.notification.flash.sequence[0].color = '#00ff88';
instance.form.notification.flash.sequence[0].duration_ms = 220;
instance.form.notification.flash.sequence[1].color = '#0044ff';
instance.form.notification.flash.sequence[1].duration_ms = 330;
instance.removeFlashStep(1);
instance.form.notification.flash.opacity = 0.45;

instance.form.notification.policy.cooldown_ms = 2500;
instance.form.notification.policy.dedupe_window_ms = 9000;

instance.onSave();

const save = instance.emitted.find((event) => event.name === 'save');
if (!save) {
  throw new Error('WorkerConfigModal did not emit save');
}

process.stdout.write(JSON.stringify(save.payload, null, 2));
