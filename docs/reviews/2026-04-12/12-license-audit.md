# Third-Party & Open-Source License Audit — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Audit of all third-party and open-source dependencies (Python backend and JavaScript frontend), their declared licenses, attribution obligations, and compatibility with distribution of the Bullpen project. Findings are based on reading `requirements.txt`, `static/index.html`, and all Python import statements in `server/` and `bullpen.py`.

---

## Dependency Inventory

### Python Dependencies (`requirements.txt`)

| Package | Version Constraint | License | Attribution Obligation |
|---------|--------------------|---------|------------------------|
| flask | (none pinned) | BSD 3-Clause | Include license text if distributing |
| flask-socketio | >=5.3.6 | MIT | None beyond inclusion |
| simple-websocket | (none pinned) | MIT | None beyond inclusion |
| websocket-client | (none pinned) | Apache 2.0 | NOTICE file required if distributing binary |
| eventlet | (none pinned) | MIT | None beyond inclusion |
| pytest | (none pinned) | MIT | Dev dependency — no distribution obligation |

**Transitive dependencies identified from imports:**

| Package | License | Notes |
|---------|---------|-------|
| werkzeug | BSD 3-Clause | Installed by Flask; `server/auth.py` imports `generate_password_hash`, `check_password_hash` |
| bidict | MPL-2.0 | Installed by python-socketio; not directly imported |
| python-socketio | MIT | Installed by flask-socketio |
| python-engineio | MIT | Installed by flask-socketio |

### JavaScript / Frontend Dependencies (`static/index.html`)

All frontend dependencies are loaded from CDN via `<script>` tags with SRI integrity attributes:

| Library | Version | CDN Source | License | SRI Hash Present |
|---------|---------|-----------|---------|-----------------|
| Vue.js | 3 (latest, no pin) | unpkg.com | MIT | Yes (crossorigin="anonymous") |
| Socket.IO Client | 4.7.5 | cdn.socket.io | MIT | Yes |
| Prism.js | 1.29.0 | cdnjs.cloudflare.com | MIT | Yes |
| markdown-it | 13.0.2 | cdnjs.cloudflare.com | MIT | Yes |
| Lucide Icons | latest (no pin) | unpkg.com | MIT | Yes |

### Standard Library (No License Obligation)

Python standard library modules (`os`, `sys`, `json`, `re`, `subprocess`, `threading`, `pathlib`, `datetime`, `secrets`, `logging`, `urllib.parse`, `shutil`, `tempfile`, `functools`, `abc`, `getpass`, `argparse`) impose no license obligations.

---

## Findings

### HIGH — No LICENSE file in repository

**Files:** Repository root (verified absent: no `LICENSE`, `LICENSE.md`, `LICENSE.txt`, or `COPYING`)

The project ships no license. This creates two problems:

1. **Inbound**: Under copyright law in most jurisdictions, code with no explicit license is "all rights reserved" by default. Contributors cannot legally submit patches without an explicit license grant.
2. **Outbound**: Users and downstream integrators have no legal basis to use, modify, or redistribute Bullpen.

All runtime dependencies (BSD, MIT, Apache 2.0) are permissive and compatible with each other and with MIT or Apache 2.0 for Bullpen itself. There is no GPL dependency that would impose copyleft obligations.

**Recommendation:** Add a `LICENSE` file (MIT or Apache 2.0 recommended) before any public distribution.

---

### MEDIUM — `websocket-client` (Apache 2.0) requires NOTICE file in binary distributions

**File:** `requirements.txt`

The Apache 2.0 license requires that binary distributions include a `NOTICE` file if the distributed package contains a `NOTICE` file. `websocket-client` ships a `NOTICE` file. If Bullpen is packaged as a binary (e.g., PyInstaller, Docker image with bundled packages), this `NOTICE` must be included.

For source distribution (git clone + pip install), no separate `NOTICE` file is needed from the distributor.

**Recommendation:** If a binary distribution is planned, include or reference the `websocket-client` NOTICE file in a top-level `NOTICES/` directory.

---

### MEDIUM — Vue.js and Lucide Icons loaded from unpkg.com without version pinning

**File:** `static/index.html`

Vue 3 is loaded as `vue@3` (no patch version) and Lucide Icons is loaded as `lucide-vue-next` (no version at all). CDN assets served without a pinned version can silently update when the CDN updates its routing:

- A breaking change in Vue 3.x.y → 3.x.(y+1) could break the frontend without any code change on the Bullpen side.
- The SRI hash for a versionless URL is hash of today's content; if CDN updates the content without the URL changing, the browser will reject the load (correct SRI behavior), but this would manifest as a silent frontend outage.

**Recommendation:** Pin all CDN dependencies to exact versions (e.g., `vue@3.4.21`, `lucide-vue-next@0.365.0`) and regenerate SRI hashes after each intentional version update.

---

### MEDIUM — `bidict` is MPL-2.0 licensed (weak copyleft)

**File:** Transitive dependency of `python-socketio` (installed by `flask-socketio`)

`bidict` is licensed under the Mozilla Public License 2.0 (MPL-2.0). MPL-2.0 is a weak copyleft license: modifications to `bidict`'s source files must be released under MPL-2.0, but combining `bidict` with Bullpen code in a larger work does not require Bullpen to adopt MPL-2.0. This is file-level copyleft, not program-level.

For source distribution of Bullpen (which does not modify `bidict`), this is not an issue. If Bullpen ever forks or patches `bidict`, those patches must be released under MPL-2.0.

**Recommendation:** No immediate action required. Document this in a `NOTICES/` file when one is created.

---

### LOW — No NOTICE or ATTRIBUTIONS file

**Files:** Repository root (verified absent: no `NOTICE`, `ATTRIBUTIONS`, or `CREDITS`)

While none of the current dependencies strictly require attribution in source distributions beyond preserving their license texts, best practice (and a requirement for Apache 2.0 binary distributions) is to include a `NOTICE` or `ATTRIBUTIONS` file crediting upstream projects. This is also a common requirement in enterprise license compliance workflows.

**Recommendation:** Add a `NOTICES/` directory listing all direct dependencies, their versions, and their license identifiers (SPDX format preferred).

---

### LOW — No dependency version pins create non-reproducible installs

**File:** `requirements.txt`

With the exception of `flask-socketio>=5.3.6`, no dependency has a pinned version. This means `pip install -r requirements.txt` at different points in time can produce different installed versions. If an upstream package releases a breaking change, installations will silently break.

This is also a license audit concern: if a dependency changes its license in a new version (rare but documented — e.g., HashiCorp BSL transition), a version-unpinned install could silently adopt the new license.

**Recommendation:** Add a `requirements.lock` or use `pip freeze > requirements-lock.txt` to capture the full pinned dependency tree for reproducible installs. For license compliance, update and audit the lock file on each dependency update.

---

## License Compatibility Assessment

| Component | License | Compatible with MIT for Bullpen? | Compatible with Apache 2.0 for Bullpen? |
|-----------|---------|----------------------------------|------------------------------------------|
| flask | BSD 3-Clause | Yes | Yes |
| werkzeug | BSD 3-Clause | Yes | Yes |
| flask-socketio | MIT | Yes | Yes |
| python-socketio | MIT | Yes | Yes |
| python-engineio | MIT | Yes | Yes |
| simple-websocket | MIT | Yes | Yes |
| websocket-client | Apache 2.0 | Yes | Yes |
| eventlet | MIT | Yes | Yes |
| bidict | MPL-2.0 | Yes (file-level copyleft only) | Yes (file-level copyleft only) |
| Vue.js | MIT | N/A (frontend, not distributed with server) | N/A |
| Socket.IO Client | MIT | N/A | N/A |
| Prism.js | MIT | N/A | N/A |
| markdown-it | MIT | N/A | N/A |
| Lucide Icons | MIT | N/A | N/A |

**No GPL or AGPL dependencies detected.** There is no license incompatibility risk in the current dependency tree.

---

## Positive Observations

- All runtime Python dependencies are permissively licensed (BSD, MIT, Apache 2.0, MPL-2.0 weak copyleft). No GPL contamination.
- All frontend CDN dependencies are MIT. No copyleft or commercial restrictions.
- SRI integrity attributes are present on all `<script>` tags in `static/index.html`, preventing CDN compromise from silently injecting code.
- `pytest` is a dev-only dependency with no distribution obligation.

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| LC1 | HIGH | No LICENSE file — undefined terms for users and contributors |
| LC2 | MEDIUM | `websocket-client` Apache 2.0 NOTICE required in binary distributions |
| LC3 | MEDIUM | Vue.js and Lucide Icons loaded without version pinning from CDN |
| LC4 | MEDIUM | `bidict` (MPL-2.0 transitive dep) — file-level copyleft if forked |
| LC5 | LOW | No NOTICE/ATTRIBUTIONS file for dependency attribution |
| LC6 | LOW | Unpinned dependencies create non-reproducible installs and silent license drift |
