(function () {
  const COMMAND_PREFIX = '>';

  function splitQuickCreateText(text) {
    const raw = String(text || '').trim();
    if (!raw) return { title: '', description: '' };
    const slashIdx = raw.indexOf('/');
    return slashIdx >= 0
      ? {
          title: raw.slice(0, slashIdx).trim(),
          description: raw.slice(slashIdx + 1).trim(),
        }
      : { title: raw, description: '' };
  }

  function parseCommandInput(input) {
    const raw = String(input || '').trim();
    const text = raw.startsWith(COMMAND_PREFIX) ? raw.slice(1).trim() : raw;
    const spaceIdx = text.indexOf(' ');
    return {
      raw,
      text,
      command: (spaceIdx >= 0 ? text.slice(0, spaceIdx) : text).toLowerCase(),
      args: spaceIdx >= 0 ? text.slice(spaceIdx + 1).trim() : '',
    };
  }

  const QUICK_CALCULATE_MAX_LENGTH = 500;
  const QUICK_CALCULATE_CONSTANTS = {
    e: Math.E,
    pi: Math.PI,
    tau: Math.PI * 2,
  };
  const QUICK_CALCULATE_FUNCTIONS = {
    abs: { min: 1, max: 1, fn: Math.abs },
    acos: { min: 1, max: 1, fn: Math.acos },
    asin: { min: 1, max: 1, fn: Math.asin },
    atan: { min: 1, max: 1, fn: Math.atan },
    atan2: { min: 2, max: 2, fn: Math.atan2 },
    ceil: { min: 1, max: 1, fn: Math.ceil },
    cos: { min: 1, max: 1, fn: Math.cos },
    exp: { min: 1, max: 1, fn: Math.exp },
    floor: { min: 1, max: 1, fn: Math.floor },
    ln: { min: 1, max: 1, fn: Math.log },
    log: { min: 1, max: 2, fn: (value, base) => base === undefined ? Math.log(value) : Math.log(value) / Math.log(base) },
    log10: { min: 1, max: 1, fn: Math.log10 },
    max: { min: 1, max: Infinity, fn: Math.max },
    min: { min: 1, max: Infinity, fn: Math.min },
    pow: { min: 2, max: 2, fn: Math.pow },
    round: { min: 1, max: 1, fn: Math.round },
    sin: { min: 1, max: 1, fn: Math.sin },
    sqrt: { min: 1, max: 1, fn: Math.sqrt },
    tan: { min: 1, max: 1, fn: Math.tan },
  };

  function formatQuickCalculateResult(value) {
    const normalized = Object.is(value, -0) ? 0 : value;
    if (Number.isInteger(normalized)) return String(normalized);
    const rounded = Number(normalized.toPrecision(12));
    return String(Object.is(rounded, -0) ? 0 : rounded);
  }

  class QuickCalculateParser {
    constructor(expression) {
      this.expression = expression;
      this.index = 0;
    }

    parse() {
      const value = this.parseExpression();
      this.skipWhitespace();
      if (!this.isAtEnd()) throw this.error(`Unexpected "${this.peek()}"`);
      this.requireFinite(value);
      return value;
    }

    parseExpression() {
      return this.parseAdditive();
    }

    parseAdditive() {
      let value = this.parseMultiplicative();
      for (;;) {
        if (this.match('+')) {
          value += this.parseMultiplicative();
        } else if (this.match('-')) {
          value -= this.parseMultiplicative();
        } else {
          return this.requireFinite(value);
        }
      }
    }

    parseMultiplicative() {
      let value = this.parsePower();
      for (;;) {
        if (this.startsWith('**')) return this.requireFinite(value);
        if (this.match('*')) {
          value *= this.parsePower();
        } else if (this.match('/')) {
          const divisor = this.parsePower();
          if (divisor === 0) throw this.error('Division by zero');
          value /= divisor;
        } else if (this.match('%')) {
          const divisor = this.parsePower();
          if (divisor === 0) throw this.error('Division by zero');
          value %= divisor;
        } else {
          return this.requireFinite(value);
        }
      }
    }

    parsePower() {
      const value = this.parseUnary();
      if (this.match('**') || this.match('^')) {
        return this.requireFinite(Math.pow(value, this.parsePower()));
      }
      return this.requireFinite(value);
    }

    parseUnary() {
      if (this.match('+')) return this.parseUnary();
      if (this.match('-')) return this.requireFinite(-this.parseUnary());
      return this.parsePrimary();
    }

    parsePrimary() {
      this.skipWhitespace();
      if (this.match('(')) {
        const value = this.parseExpression();
        this.expect(')', 'Expected ")"');
        return this.requireFinite(value);
      }
      const char = this.peek();
      if (this.isDigit(char) || char === '.') return this.parseNumber();
      if (this.isIdentifierStart(char)) return this.parseIdentifier();
      throw this.error('Expected a number, function, constant, or "("');
    }

    parseNumber() {
      const start = this.index;
      let sawDigit = false;
      while (this.isDigit(this.peek())) {
        sawDigit = true;
        this.index++;
      }
      if (this.peek() === '.') {
        this.index++;
        while (this.isDigit(this.peek())) {
          sawDigit = true;
          this.index++;
        }
      }
      if (!sawDigit) throw this.error('Expected a number');
      if (this.peek() === 'e' || this.peek() === 'E') {
        const exponentStart = this.index;
        this.index++;
        if (this.peek() === '+' || this.peek() === '-') this.index++;
        let sawExponentDigit = false;
        while (this.isDigit(this.peek())) {
          sawExponentDigit = true;
          this.index++;
        }
        if (!sawExponentDigit) {
          this.index = exponentStart;
          throw this.error('Invalid exponent');
        }
      }
      const value = Number(this.expression.slice(start, this.index));
      return this.requireFinite(value);
    }

    parseIdentifier() {
      const start = this.index;
      this.index++;
      while (this.isIdentifierPart(this.peek())) this.index++;
      const name = this.expression.slice(start, this.index).toLowerCase();
      if (this.match('(')) {
        const args = this.parseArguments();
        const fn = QUICK_CALCULATE_FUNCTIONS[name];
        if (!fn) throw this.error(`Unknown function "${name}"`);
        if (args.length < fn.min || args.length > fn.max) {
          const expected = fn.max === Infinity
            ? `at least ${fn.min}`
            : (fn.min === fn.max ? String(fn.min) : `${fn.min}-${fn.max}`);
          const plural = expected === '1' || expected === 'at least 1' ? '' : 's';
          throw this.error(`Function "${name}" expects ${expected} argument${plural}`);
        }
        return this.requireFinite(fn.fn(...args));
      }
      if (Object.prototype.hasOwnProperty.call(QUICK_CALCULATE_CONSTANTS, name)) {
        return QUICK_CALCULATE_CONSTANTS[name];
      }
      throw this.error(`Unknown constant "${name}"`);
    }

    parseArguments() {
      const args = [];
      this.skipWhitespace();
      if (this.match(')')) return args;
      for (;;) {
        args.push(this.parseExpression());
        this.skipWhitespace();
        if (this.match(')')) return args;
        this.expect(',', 'Expected "," or ")"');
      }
    }

    match(token) {
      this.skipWhitespace();
      if (!this.expression.startsWith(token, this.index)) return false;
      this.index += token.length;
      return true;
    }

    expect(token, message) {
      if (!this.match(token)) throw this.error(message);
    }

    startsWith(token) {
      this.skipWhitespace();
      return this.expression.startsWith(token, this.index);
    }

    skipWhitespace() {
      while (/\s/.test(this.peek())) this.index++;
    }

    peek() {
      return this.expression[this.index] || '';
    }

    isAtEnd() {
      return this.index >= this.expression.length;
    }

    isDigit(char) {
      return char >= '0' && char <= '9';
    }

    isIdentifierStart(char) {
      return /^[A-Za-z_]$/.test(char);
    }

    isIdentifierPart(char) {
      return /^[A-Za-z0-9_]$/.test(char);
    }

    requireFinite(value) {
      if (!Number.isFinite(value)) throw this.error('Result is not finite');
      return value;
    }

    error(message) {
      return new Error(`${message} at position ${this.index + 1}`);
    }
  }

  function evaluateQuickCalculate(input) {
    const raw = String(input || '').trimStart();
    if (!raw.startsWith('=')) {
      return { ok: false, expression: '', error: 'Quick calculate expressions must start with =' };
    }
    const expression = raw.slice(1).trim();
    if (!expression) return { ok: false, expression: '', error: 'Expression is empty' };
    if (expression.length > QUICK_CALCULATE_MAX_LENGTH) {
      return { ok: false, expression, error: `Expression is longer than ${QUICK_CALCULATE_MAX_LENGTH} characters` };
    }
    try {
      const value = new QuickCalculateParser(expression).parse();
      return { ok: true, expression, value, result: formatQuickCalculateResult(value) };
    } catch (err) {
      return { ok: false, expression, error: err?.message || 'Invalid expression' };
    }
  }

  function normalize(value) {
    return String(value || '').trim().toLowerCase();
  }

  function requireWorkspace(ctx) {
    return ctx?.activeWorkspaceId ? true : 'Open a project first';
  }

  function command(definition) {
    return {
      aliases: [],
      keywords: [],
      shortcut: '',
      prefixes: [COMMAND_PREFIX],
      ...definition,
    };
  }

  function buildCommands(ctx = {}) {
    const themes = Array.isArray(ctx.themes) ? ctx.themes : [];
    const ambientPresets = Array.isArray(ctx.ambientPresets) ? ctx.ambientPresets : [];

    const commands = [
      command({
        id: 'ticket.create',
        title: 'Create Ticket',
        subtitle: 'Create a new ticket in the active project',
        group: 'Tickets',
        aliases: ['new', 'ticket', 'create', 'new ticket'],
        keywords: ['issue', 'task', 'todo'],
        shortcut: 'Enter',
        available: requireWorkspace,
        run(runCtx, args) {
          const payload = splitQuickCreateText(args);
          if (!payload.title) {
            runCtx.actions.openCreateModal();
            return;
          }
          runCtx.actions.quickCreateTask(payload);
        },
      }),
      command({
        id: 'ticket.archive_done',
        title: 'Archive Done Tickets',
        subtitle: 'Archive all tickets in Done after confirmation',
        group: 'Tickets',
        aliases: ['archive done', 'archive'],
        keywords: ['clean up', 'done'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.archiveDone(),
      }),
      command({
        id: 'tickets.scope.live',
        title: 'Show Live Tickets',
        subtitle: 'Switch the ticket list to live tickets',
        group: 'Tickets',
        aliases: ['live', 'scope live', 'show live'],
        available: requireWorkspace,
        run(runCtx) {
          runCtx.actions.setTicketListScope('live');
          runCtx.actions.setActiveTab('tasks');
        },
      }),
      command({
        id: 'tickets.scope.archived',
        title: 'Show Archived Tickets',
        subtitle: 'Switch the ticket list to archived tickets',
        group: 'Tickets',
        aliases: ['archived', 'archive list', 'scope archived'],
        available: requireWorkspace,
        run(runCtx) {
          runCtx.actions.setTicketListScope('archived');
          runCtx.actions.setActiveTab('tasks');
        },
      }),
      command({
        id: 'tickets.scope',
        title: 'Set Ticket Scope',
        subtitle: 'Use live or archived',
        group: 'Tickets',
        aliases: ['scope'],
        available: requireWorkspace,
        run(runCtx, args) {
          const scope = normalize(args);
          if (scope !== 'live' && scope !== 'archived') {
            runCtx.actions.addToast('Usage: >scope live|archived', 'error');
            return;
          }
          runCtx.actions.setTicketListScope(scope);
          runCtx.actions.setActiveTab('tasks');
        },
      }),
      command({
        id: 'tickets.view.kanban',
        title: 'Tickets: Kanban View',
        subtitle: 'Show tickets as columns',
        group: 'Views',
        aliases: ['kanban', 'view kanban'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.setTicketsViewMode('kanban'),
      }),
      command({
        id: 'tickets.view.list',
        title: 'Tickets: List View',
        subtitle: 'Show tickets as a searchable list',
        group: 'Views',
        aliases: ['list', 'view list'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.setTicketsViewMode('list'),
      }),
      command({
        id: 'tickets.view',
        title: 'Set Ticket View',
        subtitle: 'Use kanban or list',
        group: 'Views',
        aliases: ['view'],
        available: requireWorkspace,
        run(runCtx, args) {
          const mode = normalize(args);
          if (mode !== 'kanban' && mode !== 'list') {
            runCtx.actions.addToast('Usage: >view kanban|list', 'error');
            return;
          }
          runCtx.actions.setTicketsViewMode(mode);
        },
      }),
      command({
        id: 'tab.open',
        title: 'Open Tab',
        subtitle: 'Use tickets, workers, files, git, or chat',
        group: 'Views',
        aliases: ['tab', 'open tab'],
        keywords: ['navigation'],
        available: requireWorkspace,
        run(runCtx, args) {
          if (!runCtx.actions.openStandardTab(args)) {
            runCtx.actions.addToast(`Unknown tab "${args}"`, 'error');
          }
        },
      }),
      command({
        id: 'tab.tickets',
        title: 'Open Tickets',
        subtitle: 'Switch to the Tickets tab',
        group: 'Views',
        aliases: ['tickets', 'tasks', 'open tickets'],
        keywords: ['tab', 'navigation'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.setActiveTab('tasks'),
      }),
      command({
        id: 'tab.workers',
        title: 'Open Workers',
        subtitle: 'Switch to the Workers tab',
        group: 'Views',
        aliases: ['workers', 'bullpen', 'open workers'],
        keywords: ['tab', 'navigation'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.setActiveTab('workers'),
      }),
      command({
        id: 'tab.files',
        title: 'Open Files',
        subtitle: 'Switch to the Files tab',
        group: 'Views',
        aliases: ['files', 'open files'],
        keywords: ['tab', 'navigation'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.setActiveTab('files'),
      }),
      command({
        id: 'tab.commits',
        title: 'Open Git',
        subtitle: 'Switch to the Git tab',
        group: 'Views',
        aliases: ['git', 'commits', 'open git', 'open commits'],
        keywords: ['tab', 'navigation'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.setActiveTab('commits'),
      }),
      command({
        id: 'tab.chat',
        title: 'Open Agent Chat',
        subtitle: 'Switch to or create an agent chat tab',
        group: 'Chat',
        aliases: ['chat', 'live', 'open chat'],
        keywords: ['tab', 'navigation'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.openChatTab(),
      }),
      command({
        id: 'chat.new',
        title: 'New Agent Chat',
        subtitle: 'Create a new agent chat tab',
        group: 'Chat',
        aliases: ['new chat', 'add chat'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.addLiveAgentTab({ activate: true }),
      }),
      command({
        id: 'pane.left.toggle',
        title: 'Toggle Left Pane',
        subtitle: 'Show or hide the project and queue pane',
        group: 'Views',
        aliases: ['left', 'pane', 'toggle left pane', 'toggle-left-pane'],
        run: runCtx => runCtx.actions.toggleLeftPane(),
      }),
      command({
        id: 'columns.manage',
        title: 'Manage Columns',
        subtitle: 'Open the column manager',
        group: 'Columns',
        aliases: ['columns', 'manage columns'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.openColumnManager(),
      }),
      command({
        id: 'project.export',
        title: 'Export This Project',
        subtitle: 'Download the active project as a zip',
        group: 'Project',
        aliases: ['export project', 'export workspace'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.exportWorkspace(),
      }),
      command({
        id: 'workers.export',
        title: 'Export Workers',
        subtitle: 'Download worker configuration for the active project',
        group: 'Project',
        aliases: ['export workers'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.exportWorkers(),
      }),
      command({
        id: 'project.export_all',
        title: 'Export All Projects',
        subtitle: 'Download all Bullpen project data as a zip',
        group: 'Project',
        aliases: ['export all'],
        run: runCtx => runCtx.actions.exportAll(),
      }),
      command({
        id: 'project.import',
        title: 'Import...',
        subtitle: 'Import a Bento package, project zip, or all-workspace zip',
        group: 'Project',
        aliases: ['import', 'import project', 'import workspace', 'import package', 'import workers', 'import bento', 'import all'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.importAnyFromPicker(),
      }),
      command({
        id: 'theme.change',
        title: 'Change Theme',
        subtitle: 'Use a theme id or label',
        group: 'Preferences',
        aliases: ['theme', 'set theme'],
        run(runCtx, args) {
          const query = normalize(args);
          if (!query) {
            runCtx.actions.addToast(`Themes: ${themes.map(t => t.id).join(', ')}`);
            return;
          }
          const match = themes.find(t => normalize(t.id) === query || normalize(t.label) === query);
          if (!match) {
            runCtx.actions.addToast(`Unknown theme "${args}"`, 'error');
            return;
          }
          runCtx.actions.setTheme(match.id);
        },
      }),
      command({
        id: 'ambient.change',
        title: 'Set Ambient Sound',
        subtitle: 'Use an ambient preset id or off',
        group: 'Preferences',
        aliases: ['ambient', 'sound', 'set ambient'],
        available: requireWorkspace,
        run(runCtx, args) {
          const query = normalize(args);
          if (!query || query === 'off' || query === 'none') {
            runCtx.actions.setAmbientPreset('');
            return;
          }
          const match = ambientPresets.find(p => normalize(p.key) === query || normalize(p.label) === query);
          if (!match) {
            runCtx.actions.addToast(`Unknown ambient preset "${args}"`, 'error');
            return;
          }
          runCtx.actions.setAmbientPreset(match.key);
        },
      }),
      command({
        id: 'ambient.off',
        title: 'Turn Ambient Sound Off',
        subtitle: 'Disable ambient background sound',
        group: 'Preferences',
        aliases: ['ambient off', 'sound off'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.setAmbientPreset(''),
      }),
      command({
        id: 'volume.set',
        title: 'Set Ambient Volume',
        subtitle: 'Use a number from 0 to 100',
        group: 'Preferences',
        aliases: ['volume', 'set volume'],
        available: requireWorkspace,
        run(runCtx, args) {
          const value = Number(args);
          if (!Number.isFinite(value)) {
            runCtx.actions.addToast('Usage: >volume 0-100', 'error');
            return;
          }
          runCtx.actions.setAmbientVolume(value);
        },
      }),
      command({
        id: 'help.commands',
        title: 'Show Commands',
        subtitle: 'Open command mode and browse available commands',
        group: 'Help',
        aliases: ['help', 'commands'],
        run: runCtx => runCtx.actions.addToast('Type > and start typing to search commands.'),
      }),
      command({
        id: 'project.copy_path',
        title: 'Copy Project Name',
        subtitle: 'Copy the active project name to the clipboard',
        group: 'Help',
        aliases: ['copy path', 'workspace path'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.copyText('Project name', runCtx.projectPath),
      }),
      command({
        id: 'project.copy_id',
        title: 'Copy Project ID',
        subtitle: 'Copy the active project id to the clipboard',
        group: 'Help',
        aliases: ['copy project id', 'project id'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.copyText('Project ID', runCtx.activeWorkspaceId),
      }),
    ];

    for (const theme of themes) {
      commands.push(command({
        id: `theme.${theme.id}`,
        title: `Theme: ${theme.label}`,
        subtitle: `Switch to ${theme.label}`,
        group: 'Preferences',
        aliases: [theme.id, theme.label, `${theme.label} theme`],
        keywords: ['theme', 'color'],
        run: runCtx => runCtx.actions.setTheme(theme.id),
      }));
    }

    for (const preset of ambientPresets) {
      commands.push(command({
        id: `ambient.${preset.key}`,
        title: `Ambient: ${preset.label}`,
        subtitle: `Switch ambient sound to ${preset.label}`,
        group: 'Preferences',
        aliases: [preset.key, preset.label, `${preset.label} ambient`],
        keywords: ['ambient', 'sound'],
        available: requireWorkspace,
        run: runCtx => runCtx.actions.setAmbientPreset(preset.key),
      }));
    }

    return commands.map(definition => {
      let disabledReason = '';
      if (typeof definition.available === 'function') {
        const available = definition.available(ctx);
        if (available !== true) disabledReason = available || 'Unavailable';
      }
      return { ...definition, disabledReason };
    });
  }

  function searchableText(command) {
    return [
      command.id,
      command.title,
      command.subtitle,
      command.group,
      ...(command.aliases || []),
      ...(command.keywords || []),
    ].map(normalize).join(' ');
  }

  function scoreCommand(command, query) {
    const q = normalize(query);
    if (!q) return command.disabledReason ? 5 : 10;
    const haystack = searchableText(command);
    const title = normalize(command.title);
    const aliases = (command.aliases || []).map(normalize);
    const tokens = q.split(/\s+/).filter(Boolean);
    let score = command.disabledReason ? -5 : 0;
    for (const token of tokens) {
      if (aliases.includes(token) || normalize(command.id) === token) score += 100;
      else if (title === token) score += 90;
      else if (title.startsWith(token)) score += 60;
      else if (aliases.some(alias => alias.startsWith(token))) score += 55;
      else if (haystack.includes(token)) score += 20;
      else return 0;
    }
    return score;
  }

  function filterCommands(commands, query, limit = 12) {
    return (commands || [])
      .map(cmd => ({ cmd, score: scoreCommand(cmd, query) }))
      .filter(item => item.score > 0)
      .sort((a, b) => b.score - a.score || a.cmd.title.localeCompare(b.cmd.title))
      .slice(0, limit)
      .map(item => item.cmd);
  }

  function commandMatches(command, token) {
    const needle = normalize(token);
    if (!needle) return false;
    return normalize(command.id) === needle
      || normalize(command.title) === needle
      || (command.aliases || []).some(alias => normalize(alias) === needle);
  }

  function findCommand(commands, input) {
    const parsed = parseCommandInput(input);
    if (!parsed.command) return null;
    const exact = (commands || []).find(cmd => commandMatches(cmd, parsed.command));
    if (exact) return { command: exact, args: parsed.args, parsed };
    const fuzzy = filterCommands(commands, parsed.text, 1)[0];
    return fuzzy ? { command: fuzzy, args: parsed.args, parsed } : null;
  }

  window.BullpenCommands = {
    COMMAND_PREFIX,
    splitQuickCreateText,
    parseCommandInput,
    evaluateQuickCalculate,
    buildCommands,
    filterCommands,
    findCommand,
  };
})();
