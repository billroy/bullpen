# Report Browser: Specification and Handoff

## Purpose

Build a small, per-project Flask application that presents generated HTML work
products as a reverse-chronological list with a selected-report detail view.
The application is intended to run under a Bullpen Service worker and is a
maintainable step up from `python -m http.server`.

The first implementation will live in the `news` project. It must remain
project-local: it reads reports from that project and does not read or write any
other Bullpen workspace.

## User experience

Opening the Service worker's site shows a two-pane page:

- The left pane lists HTML reports, newest first.
- Each list item shows a title and modification date.
- The right pane displays the selected report.
- The newest report is selected when no explicit selection is present.
- Selecting a report reloads the page with that report selected.
- Refreshing the page discovers newly generated reports immediately.
- A useful empty state is shown when the report directory contains no HTML.

On narrow screens, the panes may stack vertically.

## Proposed project layout

The concrete location of the application inside `news` may be adjusted to fit
that repository, but keep the Flask code, Jinja template, and local CSS as
separate files:

```text
news/
├── reports/                         # Example only; selected with --root
└── report_browser/
    ├── app.py
    ├── templates/
    │   └── index.html
    └── static/
        └── report-browser.css
```

Do not embed the page frame, CSS, or JavaScript as strings in `app.py`.

## Command-line interface

The report directory must be configurable on the command line. Use a required
`--root` option rather than fixing the directory name in code:

```bash
python3 report_browser/app.py --root reports --port 3100
```

Required option:

- `--root PATH`: Directory containing report HTML and associated assets. A
  relative path is resolved against the process working directory.

Recommended options:

- `--host HOST`: Bind address. Default: `127.0.0.1`.
- `--port PORT`: Listening port. Default: the `PORT` environment variable when
  set, otherwise `3100`.
- `--title TEXT`: Page heading. Default: `Reports`.
- `--bullpen-css-url URL`: URL of Bullpen's main stylesheet. Default: the
  `BULLPEN_CSS_URL` environment variable, if set; otherwise omit the external
  stylesheet link.

`--root` is authoritative. Do not add a `REPORT_ROOT` environment-variable
fallback in the first version; requiring the path in the Service worker command
makes the served boundary visible during configuration and review.

At startup, resolve `--root` to an absolute, canonical path. Exit with a clear,
non-zero error if it does not exist or is not a directory. Log the resolved
report root and listening URL without logging report contents.

## Flask routes

### `GET /`

Render `templates/index.html` with:

- The configured page title.
- The reports sorted newest-first.
- The selected report.
- The optional Bullpen stylesheet URL.

Accept an optional `item` query parameter containing a report path relative to
the configured root:

```text
/?item=2026/08/30/evening-news.html
```

If `item` is absent, select the newest report. If it is invalid, outside the
root, missing, or not an HTML file, return a normal page with a clear
not-found/invalid-selection message; do not silently serve another file.

List links should be ordinary server-rendered links. The first version does not
need an API or client-side state framework.

### `GET /content/<path:report_path>`

Serve report HTML and its relative assets from the configured report root.
This route exists so reports containing relative images, stylesheets, fonts, or
scripts can render correctly.

Every requested path must be resolved and verified to remain within the
canonical report root. Reject traversal and symlink escapes. Directory listing
is not supported. Missing files return 404.

The index page should load the selected HTML URL in an iframe. Begin with:

```html
<iframe sandbox="allow-scripts" ...></iframe>
```

Do not add `allow-same-origin`. This allows report scripts when needed while
giving the document an opaque origin. If the current `news` reports do not need
scripts, a stricter empty `sandbox` attribute is preferable.

### `GET /health`

Return HTTP 200 with a small JSON response:

```json
{"ok": true}
```

The health route should not scan or parse every report.

## Report discovery and metadata

On each request to `/`, recursively find regular `.html` and `.htm` files under
the configured root. Do not maintain a database, cache, manifest, watcher, or
generated index in the first version.

For each report, expose at least:

- `path`: POSIX-style path relative to the configured root.
- `title`: The document's `<title>` text, falling back to the filename stem.
- `modified_at`: Filesystem modification time.
- `modified_display`: A human-readable local-time representation for the page.

Use Python's standard-library HTML parser for title extraction rather than a
regular expression. Read only enough of the file to find the title, and handle
invalid encodings with replacement rather than failing the entire index.

Sort by modification time descending, with relative path as a deterministic
secondary key. Ignore unreadable files and log a concise warning.

Assets such as CSS and images are served by `/content/`, but only `.html` and
`.htm` files appear in the report list.

## Templates and styling

`templates/index.html` owns the semantic page frame. It should contain:

- A header with the configured title and a refresh link/button.
- A report-list navigation region.
- A main detail region containing the iframe or empty/error state.
- Accessible labels and a visible selected state.
- A viewport meta tag and meaningful document title.

When configured, load Bullpen's main stylesheet before the local stylesheet:

```html
{% if bullpen_css_url %}
<link rel="stylesheet" href="{{ bullpen_css_url }}">
{% endif %}
<link rel="stylesheet"
      href="{{ url_for('static', filename='report-browser.css') }}">
```

`static/report-browser.css` owns the complete structural layout and must leave
the page usable when Bullpen's stylesheet cannot be loaded. Reuse Bullpen's
general visual vocabulary where practical—color variables, typography,
borders, buttons, and empty-state treatment—but do not depend on Bullpen's
application layout selectors.

The external stylesheet URL is expected to look like:

```text
http://127.0.0.1:5050/style.css
```

Keep it configurable because the Bullpen port can differ between installations.
Do not copy Bullpen's full stylesheet into the `news` repository.

## Security boundaries

- Bind to `127.0.0.1` by default.
- Treat the configured report root as the only readable content boundary.
- Canonicalize and validate every content and selection path.
- Reject absolute paths, `..` traversal, and symlinks resolving outside root.
- Do not provide upload, edit, rename, or delete operations.
- Do not execute report files or derive shell commands from filenames.
- Escape all report-derived text rendered into the page frame; rely on Jinja's
  autoescaping and do not mark titles or paths safe.
- Render report documents only in the sandboxed iframe, never inline in the
  page frame.
- Do not store Bullpen credentials or expose environment variables.

The report server runs on a different port from Bullpen, which creates a
separate browser origin. The iframe sandbox remains required because reports
may be generated from untrusted or externally sourced material.

## Bullpen Service worker configuration

Example configuration for the `news` workspace:

```text
Name: Report Browser
Type: Service
Working directory: project root
Command: python3 report_browser/app.py --root reports --port "$PORT" --title "News Reports" --bullpen-css-url "http://127.0.0.1:5050/style.css"
Port: 3100
Health URL: http://127.0.0.1:3100/health
```

Bullpen seeds `PORT` from the Service worker's Port field. The explicit
`--port "$PORT"` keeps direct and supervised invocation behavior obvious.
Use Bullpen's existing start, stop, restart, logs, health status, and **Open site
in browser** controls; no Bullpen server or UI modifications are required.

If the `news` repository already uses a dependency-management convention, add
Flask through that convention. Otherwise, document the required Flask version
in the repository rather than relying silently on Bullpen's own environment.

## Acceptance criteria

1. `python3 report_browser/app.py --root PATH --port PORT` starts the application.
2. A missing or invalid `--root` fails immediately with a useful message.
3. `/health` returns 200 without scanning the collection.
4. `/` lists nested HTML reports newest-first.
5. Titles come from `<title>` with a filename fallback.
6. With no selection, the newest report is displayed.
7. Selecting a report updates the iframe and visible selected state.
8. Relative report assets load through `/content/`.
9. Traversal and escaping symlinks cannot read outside the configured root.
10. Generated report markup cannot alter the surrounding page frame.
11. The page remains usable without Bullpen CSS and visually aligns with
    Bullpen when the configured stylesheet is available.
12. A Bullpen Service worker can supervise and open the application using only
    project-local access.

## Suggested tests

Use Flask's test client and a temporary report tree to cover:

- Empty collection.
- Newest-first ordering and deterministic ties.
- Nested reports and assets.
- `<title>` extraction, missing titles, malformed HTML, and invalid UTF-8.
- Valid selection and missing selection.
- Absolute paths, traversal attempts, encoded traversal, and symlink escapes.
- Non-HTML files excluded from the list but available as valid report assets.
- Missing asset and missing report responses.
- Health response independent of report-directory contents.
- Optional Bullpen stylesheet link included and omitted correctly.

## Non-goals for the first version

- Aggregating reports across Bullpen projects.
- Modifying or deleting reports.
- Persistent metadata, registration, or indexing state.
- Search, tags, feeds, pagination, or authentication.
- Live updates without a page refresh.
- Changes to Bullpen's Files tab or other Bullpen UI.

## Handoff notes

Continue implementation in the `news` project, not in the Bullpen repository.
Before choosing filenames or dependency files, inspect that project's existing
layout and conventions. Keep the initial change narrow: Flask application,
Jinja template, local stylesheet, tests, and brief run instructions.

Start by running the application directly against the real `news` output
directory. Once direct operation and tests pass, configure the Bullpen Service
worker and verify its health and **Open site in browser** behavior. Do not add
cross-workspace discovery or Bullpen application changes as part of the first
implementation.
