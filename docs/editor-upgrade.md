# Files Tab Editor Upgrade

First draft: 2026-05-25
Planning inputs resolved: 2026-05-25

## Summary

Replace the Files tab edit-mode `<textarea>` with Ace Editor. The upgraded editor should make Bullpen's in-browser file edits meaningfully better without turning the Files tab into a full IDE.

The first implementation applies to every file the current server-backed Files tab can safely edit: text-like workspace files under 1 MB, excluding images, PDFs, and server-rejected binary content. This intentionally expands the older product wording that limited editing to markdown and plain text. The main `docs/spec.md` Files tab section should be updated alongside implementation so the product spec and behavior agree.

## Goals

- Syntax highlighting while editing.
- Line numbers.
- Built-in single-file find and replace with regex, match-case, and whole-word controls.
- Manual Tab behavior: pressing Tab indents the current selection or inserts the configured indentation at the cursor. The editor must not infer, rewrite, or auto-correct indentation on its own.
- Word wrap at the editor viewport edge, enabled by default, with a path to add a toggle later.
- `Cmd/Ctrl+S` saves the active edit.
- Current Files tab safety properties remain intact: workspace-scoped URLs, auth redirect handling, path validation through the existing API, binary rejection, and the 1 MB edit guard.

## Non-Goals

- No build step, bundler, npm install, Vite, or Webpack.
- No Monaco-style IDE features such as IntelliSense, project-wide search, diagnostics, minimap, or language servers.
- No background syntax linting in the first pass.
- No multi-file replace.
- No collaborative editing or conflict resolution beyond the current "discard unsaved changes before switching files" behavior.
- No per-tab editor session preservation in the first pass.
- No automated intervention in the text except syntax highlighting. Specifically: no bracket matching, auto-pairing, auto-closing quotes/brackets/tags, auto-indent on newline, formatting, autocomplete, lint popups, suggestions, or other unsolicited editor behavior.

## Current State

| Capability | Today |
|---|---|
| Edit widget | Plain `<textarea>` |
| Syntax highlighting in edit mode | None |
| Syntax highlighting in view mode | Prism.js |
| Find/replace | Hand-rolled in `FilesTab.js` |
| Line numbers | None |
| Bracket matching | None |
| Auto-indent | None |
| Word wrap toggle | None |
| Language awareness in edit mode | None |

`FilesTab.js` currently edits `editContent` through a textarea and saves with `PUT /api/files/<path>`. It allows editing for non-image/non-PDF active files whose loaded content is at most 1 MB. The server separately rejects oversized and binary writes.

## Chosen Approach

Use Ace Editor through classic script tags so `FilesTab.js` can remain a classic Vue global component.

Ace is the best fit for Bullpen's current constraints because it works without a build step, has a mature CDN-friendly distribution, includes a built-in searchbox extension, lazy-loads language modes, and does not require the component/module architecture changes that CodeMirror 6 would.

Use `ace-builds@1.44.0`, verified from the package metadata on 2026-05-25. The implementation should use:

```html
<script src="https://cdn.jsdelivr.net/npm/ace-builds@1.44.0/src-min-noconflict/ace.js"
        integrity="sha384-L35+Z0msDQr3oTrDusYCefF5a2MY3q7nK5sOTBFKQvjoZi15zWLUhzXntENo8d/5"
        crossorigin="anonymous"></script>
<script src="https://cdn.jsdelivr.net/npm/ace-builds@1.44.0/src-min-noconflict/ext-searchbox.js"
        integrity="sha384-LRJtdX7s/2zXGXuVjTTV2HRBTxhSnH1RSz7octXy7QHaXSlmCvRe2esC66Ox4l8o"
        crossorigin="anonymous"></script>
```

The `basePath` must use the same exact pinned version:

```js
ace.config.set(
  'basePath',
  'https://cdn.jsdelivr.net/npm/ace-builds@1.44.0/src-min-noconflict/'
);
```

Do not use `@latest` in any Ace URL.

## Library Notes

### Ace Editor

Decision: use it.

Why:

- Works from classic scripts.
- Keeps the current Vue component loading model.
- Built-in find/replace panel via `ext-searchbox.js`.
- Line numbers, wrap mode, explicit Tab indentation, and undo history are built in.
- Language modes cover Bullpen's common file types.
- Workers can be disabled while preserving syntax highlighting.

Constraints:

- Ace uses a global `ace` API.
- Themes and modes are lazy-loaded from `basePath`.
- Lazy-loaded Ace assets do not get browser-enforced SRI when loaded dynamically from CDN. This is accepted for exact-version CDN assets; Bullpen does not vendor frontend dependencies for this feature.
- The default visual style needs Bullpen-specific sizing and theme selection.

### CodeMirror 6

Decision: keep as a future option, not the first implementation.

Why not now:

- No single classic-script build.
- A no-build setup needs import maps and CDN ESM rewriting.
- `FilesTab.js` would need module conversion or a wrapper global.
- The proposed import-map shape needs a browser spike to prove it does not duplicate CodeMirror packages.

### prism-code-editor

Decision: keep as a future smaller-footprint option, not the first implementation.

Why not now:

- Smaller ecosystem and fewer production examples.
- UMD/global path is less documented than Ace.
- ESM path has the same module-script wrinkle as CodeMirror 6.

### Monaco

Decision: eliminated.

Why:

- Too large for this feature.
- Upstream has deprecated and stopped supporting the AMD/browser-script path for new integrations.
- The supported ESM path expects worker and bundler configuration that does not fit Bullpen's no-build constraint.

## Files Tab Behavior

### Editable Files

The editor appears when `canEdit` is true:

- Active file exists.
- File is not image or PDF.
- Loaded content is no more than 1 MB.
- Server accepts the write as text.

HTML and markdown files keep their preview/source view modes when not editing. Pressing Edit opens Ace over the raw file content. Save writes the raw content back through the existing `PUT /api/files/<path>` endpoint.

Unknown text-like extensions use Ace plain-text mode.

### Lifecycle

Use one Ace instance for the active edit session.

- `startEditing()` sets `editing = true`, then creates Ace in `nextTick`.
- The editor is populated from `activeFile.content || ''`.
- `saveEdit()` reads from `this._ace.getValue()` and writes that body with the existing `filesFetch` wrapper.
- On successful save, update `activeFile.content`, destroy Ace, and exit editing.
- `cancelEdit()` destroys Ace and exits editing without modifying `activeFile.content`.
- Switching or closing the active file while editing keeps the current confirmation flow. If the user discards changes, destroy Ace and clear the edit session.
- `activeFile`, `workspaceId`, and component unmount cleanup must destroy Ace.
- `filesVersion` reloads should not overwrite the active Ace document while editing.

This first pass clears undo history when the edit session ends. It does not preserve one Ace `EditSession` per open file tab.

### Ace Configuration

Base editor configuration:

```js
this._ace = ace.edit(this.$refs.aceContainer, {
  mode: `ace/mode/${this.aceModeName}`,
  theme: this.aceThemeName,
  fontSize: 13,
  showPrintMargin: false,
  useWorker: false,
  wrap: true,
  behavioursEnabled: false,
  wrapBehavioursEnabled: false,
  enableAutoIndent: false,
  enableBasicAutocompletion: false,
  enableLiveAutocompletion: false,
  enableSnippets: false,
  highlightActiveLine: false,
  highlightGutterLine: false,
  highlightSelectedWord: false,
  displayIndentGuides: false,
  highlightIndentGuides: false,
  showFoldWidgets: false,
});
```

The implementation must also disable Ace features that alter, annotate, or decorate text without a direct user command:

- Bracket matching or bracket highlighting.
- Auto-pairing and wrapping behaviors.
- Auto-indent on newline.
- Completion popups and snippets.
- Worker-backed linting or diagnostics.
- Active-line, selected-word, gutter-line, bracket, and indent-guide highlighting.

Quiet-mode implementation notes:

- Ace exposes `behavioursEnabled`, `wrapBehavioursEnabled`, `enableAutoIndent`, `useWorker`, `highlightActiveLine`, `highlightGutterLine`, `highlightSelectedWord`, and indent-guide options directly.
- Ace does not expose a current public `highlightMatchingBrackets` option in the downloaded 1.44.0 build. Hide any residual bracket marker with scoped CSS under `.ace-host .ace_bracket { display: none; }`.
- Do not load `ace/ext/language_tools`; set autocomplete/snippet options to false defensively anyway.
- Do not use Ace snippets or completion providers.

Required command handling:

- `Cmd/Ctrl+S`: call `saveEdit()`.
- `Cmd/Ctrl+F`: Ace searchbox find.
- `Cmd/Ctrl+H`: Ace searchbox replace.
- `Cmd/Ctrl+K`: keep Bullpen's global command palette behavior. If Ace captures it in practice, add an Ace command that dispatches the same open-palette path instead of performing an editor action.

No other Ace default command should be introduced intentionally. During implementation, manually verify that `Ctrl-L`, `Ctrl-D`, `Ctrl-/`, `Ctrl-G`, `Ctrl-K`, `Cmd-K`, and `Escape` do not cause surprising text edits or block required Bullpen behavior.

### Language Mode Map

Initial map:

| Extension | Ace mode |
|---|---|
| `.js`, `.mjs`, `.jsx` | `javascript` |
| `.ts`, `.tsx` | `typescript` |
| `.py` | `python` |
| `.json` | `json` |
| `.css`, `.scss` | `css` |
| `.html`, `.htm`, `.xml`, `.svg` | `html` or `xml` as appropriate |
| `.md`, `.markdown` | `markdown` |
| `.sh`, `.bash`, `.zsh` | `sh` |
| `.yaml`, `.yml` | `yaml` |
| `.toml` | `toml` |
| no known extension | `text` |

The map should live next to the existing `prismLang` logic or replace it with shared extension helpers so view-mode highlighting and edit-mode modes do not drift silently.

### Theme Handling

Pass `currentTheme` from `app.js` into `FilesTab` as an `activeTheme` prop. `FilesTab` should watch that prop and call `_setAceTheme()` when it changes.

First pass maps Bullpen themes to two Ace themes:

- Light Bullpen themes: `ace/theme/chrome`.
- Dark Bullpen themes: `ace/theme/tomorrow_night`.

Use the same light/dark classification already present in `static/app.js`'s `THEME_CATALOG`. The implementation should add a small helper in `FilesTab.js` with the known light theme IDs (`light`, `light-ethereal`, `light-stone-teal`, `light-ivory-olive`, `eyeshade`) and treat all others as dark. This keeps the change local without introducing a global theme API.

### CDN Failure Behavior

If `window.ace` is missing when the user starts editing:

- Do not enter a blank editor state.
- Show a concise in-pane error such as "Editor failed to load."
- Keep the existing read-only file view and Download action usable.

A textarea fallback is acceptable but not required for the first implementation.

## Files To Change

### `static/index.html`

- Add the pinned `ace-builds@1.44.0` scripts after the Prism scripts.
- Include SRI and `crossorigin="anonymous"` for the top-level scripts.
- Keep all URLs pinned to the same Ace version.

### `static/app.js`

- Pass `:active-theme="currentTheme"` to `FilesTab`.

### `static/components/FilesTab.js`

- Replace the edit-mode textarea with `<div ref="aceContainer" class="ace-host"></div>`.
- Remove the hand-rolled find/replace UI and state:
  `showFind`, `showReplace`, `findText`, `replaceText`, `findCount`, and `findIndex`.
- Remove the hand-rolled find/replace methods:
  `onEditorKeydown`, `closeFind`, `updateFindCount`, `findNext`, `findPrev`,
  `_matchIndexAt`, `doReplace`, and `doReplaceAll`.
- Add Ace lifecycle helpers:
  `_createAceEditor`, `_destroyAceEditor`, `_setAceMode`, `_setAceTheme`,
  `_aceValue`, and `_aceModeForExt`.
- Add an `activeTheme` prop and watch it to update the Ace theme while editing.
- Keep `filesFetch`, `_filesUrl`, `reloadActiveFile`, and existing save endpoint behavior.
- Ensure `renderLucideIcons` still runs for toolbar icons.

### `static/style.css`

- Replace `.file-editor-textarea` rules with `.ace-host`.
- Remove `.find-replace-*` styles if no longer used.
- Add scoped CSS to hide any residual Ace bracket marker: `.ace-host .ace_bracket { display: none; }`.
- Ensure the Ace host fills the available edit panel height without causing nested scroll glitches.

### `docs/spec.md`

- Update the Files tab section to say source/text file editing is now in scope for files accepted by the Files API.
- Remove or revise the older "source code modifications happen through agents only" wording.

## Test Plan

### Static Frontend Tests

Add or update tests that assert:

- `static/index.html` includes pinned Ace `ace.js` and `ext-searchbox.js` scripts.
- The pinned script tags use the `ace-builds@1.44.0` URLs and SRI hashes listed in this spec.
- No Ace URL uses `@latest`.
- `FilesTab.js` renders `.ace-host` in edit mode.
- The old find/replace bar markup and methods are removed.
- `saveEdit()` reads from Ace rather than `editContent`.
- The 1 MB `canEdit` guard remains.
- The Ace mode map includes JS, TS, Python, JSON, CSS, HTML/XML, Markdown, shell, YAML, TOML, and fallback text.
- Ace is configured with no bracket matching, auto-pairing, auto-indent, completions, snippets, or diagnostics.
- `app.js` passes `activeTheme` into `FilesTab`, and `FilesTab` watches it.

### Backend/API Tests

Existing Files API tests should continue to pass. Add coverage if missing for:

- Writes over 1 MB are rejected.
- Binary writes are rejected.
- Raw HTML download behavior remains attachment-based.
- JSON and other text files still round-trip as text payloads.

### Browser Smoke Test

Use the in-app browser or Playwright against a running Bullpen server:

1. Open a temp workspace with sample `.js`, `.md`, `.json`, `.yaml`, and `.txt` files.
2. Open a text file in Files tab.
3. Click Edit and verify Ace renders nonblank content with line numbers.
4. Type an edit and save with the Save button.
5. Reload the file and verify the edit persisted.
6. Repeat save with `Cmd/Ctrl+S`.
7. Open find with `Cmd/Ctrl+F`; verify search highlights a match.
8. Open replace with `Cmd/Ctrl+H`; replace one match and save.
9. Start editing, make an unsaved change, switch tabs, confirm discard, and verify the original file content remains.
10. Open a file larger than 1 MB and verify Edit is unavailable and Ace is not instantiated.
11. Simulate missing Ace and verify the UI does not enter a blank edit state.

### Manual QA

- Check dark and light Bullpen themes.
- Check the editor at narrow widths and normal desktop widths.
- Check iPad/touch enough to verify that the editor is not unusable, though desktop remains the target.
- Check global Bullpen shortcuts while focus is inside Ace.
- Specifically verify `Cmd/Ctrl+K` still opens the command palette while the Ace editor has focus.
- Check that typing plain text, brackets, quotes, tags, and newlines does not trigger auto-inserted characters, auto-indentation, linting, suggestions, or bracket highlighting.

## Acceptance Criteria

- The Files tab edit mode uses Ace for all server-editable text files under 1 MB.
- Save, cancel, close, tab switch, workspace switch, and component unmount all clean up Ace correctly.
- Existing HTML preview sandboxing and raw HTML attachment behavior remain unchanged.
- The old custom find/replace implementation is gone.
- Pinned `ace-builds@1.44.0` scripts load without `@latest`.
- CDN failure does not produce a blank edit state.
- The editor is quiet: syntax highlighting is allowed, but it does not modify, complete, reindent, annotate, or decorate text without a direct user action.
- Tests cover the lifecycle, edit guard, script pinning, old-code removal, and save path.

## Implementation Plan

1. Update `docs/spec.md` so the Files tab source/text editing scope matches this spec.
2. Add the pinned Ace scripts to `static/index.html`.
3. Pass `activeTheme` from `app.js` into `FilesTab`.
4. Replace the textarea edit surface and remove the custom find/replace state, template, methods, and CSS.
5. Add the Ace lifecycle helpers, mode map, quiet-mode options, save command, and theme watcher.
6. Preserve the existing save/cancel/tab-switch/workspace-switch behavior, including the unsaved-change confirmation flow.
7. Add/update static frontend and Files API tests.
8. Run the focused tests, then run a browser smoke test for editing, save, find/replace, theme change, quiet-mode behavior, and CDN failure handling.

## Remaining Implementation Risks

- Ace 1.44.0 does not expose a public bracket-highlight toggle in the downloaded build, so bracket markers are suppressed with scoped CSS. Browser QA must verify this is sufficient.
- `Cmd/Ctrl+K` may be captured by Ace before Bullpen's global handler in some browsers. If that happens, implement an Ace command that opens the Bullpen command palette.
- Dynamic Ace mode/theme assets are loaded from exact-version CDN URLs without per-file SRI. This is accepted by policy because Bullpen does not vendor frontend dependencies for this feature.
