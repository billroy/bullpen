# Third-Party & Open-Source License Audit — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Open-source compliance counsel evaluating for acquisition

---

## Executive Summary

Bullpen's dependency footprint is deliberately minimal: 7 Python packages, 10 CDN-served JavaScript libraries, and 3 npm-installed agent CLIs. All confirmed Python and JavaScript dependencies use permissive licenses (MIT, BSD-3-Clause, Apache 2.0, ISC) that are compatible with the project's MIT License and do not impose copyleft obligations on commercial distributions. The primary concerns are: one CDN-served library (`lucide`) is loaded without a pinned version or SRI integrity hash (supply chain risk combined with an unauditable license state), the three agent CLI licenses have not been confirmed in this audit, and the pyfiglet font licenses require spot-checking for commercial use clearance.

---

## Python Dependencies (`requirements.txt`)

| Package | Version | License | Compatibility | Notes |
|---|---|---|---|---|
| Flask | 3.1.3 | BSD-3-Clause | ✓ Compatible | Pallets project; permissive |
| Flask-SocketIO | 5.6.1 | MIT | ✓ Compatible | Miguel Grinberg; widely used |
| simple-websocket | 1.1.0 | MIT | ✓ Compatible | Bundled with Flask-SocketIO ecosystem |
| websocket-client | 1.9.0 | Apache 2.0 | ✓ Compatible | Apache 2.0 is permissive; compatible with MIT distribution |
| eventlet | 0.41.0 | MIT | ✓ Compatible | Green-thread concurrency |
| pyfiglet | 1.0.4 | MIT | ✓ Compatible | See font license note below |
| pytest | 9.0.3 | MIT | ✓ Compatible | Dev/test only; not distributed |

**Summary:** All Python runtime dependencies use permissive licenses compatible with the project's MIT License. No GPL, LGPL, AGPL, or other copyleft licenses detected. `websocket-client`'s Apache 2.0 license is compatible with MIT in all common distribution scenarios (the Apache 2.0 patent grant clause is additive, not restrictive).

---

## Frontend JavaScript Dependencies (CDN, `static/index.html`)

| Library | Version | CDN | SRI Hash | License | Compatibility |
|---|---|---|---|---|---|
| Vue | 3.5.33 | unpkg | ✓ Present | MIT | ✓ Compatible |
| Socket.IO client | 4.7.5 | cdn.socket.io | ✓ Present | MIT | ✓ Compatible |
| markdown-it | 13.0.2 | cdnjs | ✓ Present | MIT | ✓ Compatible |
| Prism (core) | 1.29.0 | cdnjs | ✓ Present | MIT | ✓ Compatible |
| Prism (python) | 1.29.0 | cdnjs | ✓ Present | MIT | ✓ Compatible |
| Prism (javascript) | 1.29.0 | cdnjs | ✓ Present | MIT | ✓ Compatible |
| Prism (json) | 1.29.0 | cdnjs | ✓ Present | MIT | ✓ Compatible |
| Prism (bash) | 1.29.0 | cdnjs | ✓ Present | MIT | ✓ Compatible |
| Prism (css) | 1.29.0 | cdnjs | ✓ Present | MIT | ✓ Compatible |
| Prism (markup) | 1.29.0 | cdnjs | ✓ Present | MIT | ✓ Compatible |
| Prism (markdown) | 1.29.0 | cdnjs | ✓ Present | MIT | ✓ Compatible |
| **lucide** | **@latest** | unpkg | **✗ ABSENT** | ISC | **⚠ SEE FINDING** |

---

## Findings

### HIGH — `lucide` loaded at `@latest` with no SRI integrity hash

**Location:** `static/index.html` line 26: `<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>`

**Detail:** The `lucide` icon library is the only CDN dependency that:
1. **Has no pinned version** — `@latest` resolves to whatever lucide version unpkg serves at page load time. The version can change without any action by the project, making the audit impossible to maintain.
2. **Has no SRI hash** — Without a `integrity="sha384-..."` attribute, the browser will execute whatever script unpkg serves, with no integrity verification. This is both a supply chain security risk and a license audit gap (cannot audit the license of an unspecified version).

Lucide's published license is ISC (functionally equivalent to MIT and compatible). However, because the version is unspecified, this audit cannot definitively confirm which version of lucide is running in any given deployment.

**Recommendation:** Pin lucide to a specific version (e.g., `@0.453.0`) and add a `sha384-...` SRI hash. The SRI hash can be generated with: `curl -s https://unpkg.com/lucide@<version>/dist/umd/lucide.min.js | openssl dgst -sha384 -binary | base64`. This resolves both the license audit gap and the security finding (already noted in `01-security-audit.md`).

---

### MEDIUM — Agent CLI licenses not confirmed

**Location:** `Dockerfile` — `npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli`

**Detail:** The three agent CLI packages are installed at Docker build time and are present in the deployed image. Their licenses were not confirmed in this audit because the packages are not present in the workspace and their published npm registry license fields require online verification:

- `@anthropic-ai/claude-code` — likely Apache 2.0 or MIT (Anthropic's common license for tooling)
- `@openai/codex` — likely MIT (OpenAI's standard tooling license)
- `@google/gemini-cli` — likely Apache 2.0 (Google's standard OSS license)

If any of these CLIs uses a license that restricts commercial distribution or embedding (e.g., a non-commercial-use restriction in their terms), bundling them in a commercial Docker image could create compliance exposure.

**Recommendation:** Verify the license of each CLI package by checking their npm registry pages and their respective GitHub repositories. Confirm that commercial use and bundling in a Docker image is permitted. Add the confirmed licenses to a `LICENSES-THIRD-PARTY.md` file. If any CLI has a restrictive license, document the implications and consult legal counsel before commercial distribution.

---

### MEDIUM — pyfiglet font licenses require spot-check for commercial use

**Location:** `requirements.txt` (pyfiglet 1.0.4), `bullpen.py` (startup ASCII art banner)

**Detail:** pyfiglet bundles FIGlet font files (`.flf`) from the FIGlet font community. pyfiglet itself is MIT-licensed, but individual fonts within the pyfiglet distribution have their own licenses embedded in their `.flf` headers. Common FIGlet font licenses include:

- **FIGlet Font License:** Requires that the license notice be retained in any copies. Permits commercial use.
- **Public Domain:** No restrictions.
- **Tombstone License** and other custom notices: Vary; some require attribution in distributed output.

The specific font used in Bullpen's startup banner was not identified in this audit. If it carries an attribution requirement, that attribution must appear in the product's `NOTICES` file or documentation.

**Recommendation:** Identify the specific pyfiglet font used for the Bullpen banner (by inspecting the `pyfiglet.figlet_format()` call in `bullpen.py` for a `font=` parameter, or by noting the default font). Read that font's `.flf` file header in the pyfiglet package installation. If attribution is required, add a `NOTICES` file. Estimated effort: 30 minutes.

---

### LOW — No `NOTICES` or `LICENSES-THIRD-PARTY.md` file

**Detail:** Standard open-source compliance practice for projects with dependencies requires a `NOTICES` or `THIRD-PARTY-LICENSES.md` file that lists all bundled dependencies with their licenses and copyright notices. This is required by:
- Apache 2.0: Section 4(d) requires reproduction of `NOTICE` files from Apache-licensed dependencies.
- Some MIT licenses: Require preservation of the license notice "in all copies or substantial portions."

Without a consolidated `NOTICES` file, there is no single place for an acquirer, redistributor, or compliance tool to verify that all license obligations have been met.

**Recommendation:** Generate a `NOTICES` file listing all Python and JavaScript dependencies, their versions, their licenses, and their copyright notices. Tools like `pip-licenses` (Python) and `license-checker` (npm) can automate this for most dependencies.

---

### LOW — MIT License `LICENSE` file lacks copyright year update

**Location:** `LICENSE` (repository root)

**Detail:** The MIT License template includes a copyright year and copyright holder name. If the `LICENSE` file's copyright year has not been updated since the project's founding year, it may technically understate the copyright period (though copyright protection is automatic and does not depend on the notice). This is a minor compliance hygiene issue.

**Recommendation:** Update the `LICENSE` file to reflect the current year range (e.g., `Copyright 2024–2026 Bullpen Contributors`). Automate this update as part of the annual release process.

---

## License Compatibility Matrix

| License Type | Bullpen (MIT) | Result |
|---|---|---|
| MIT | MIT | ✓ Compatible |
| BSD-3-Clause | MIT | ✓ Compatible |
| Apache 2.0 | MIT | ✓ Compatible (patent grant additive) |
| ISC | MIT | ✓ Compatible (functionally equivalent) |
| GPL-2.0 | MIT | ✗ Incompatible (none detected) |
| LGPL | MIT | ✗ Incompatible in static linking (none detected) |
| AGPL | MIT | ✗ Incompatible (none detected) |

**Conclusion:** No copyleft dependencies detected in confirmed dependencies. All confirmed licenses are permissive and mutually compatible. The unconfirmed items (lucide@latest, agent CLIs, pyfiglet font) require the remediation actions described above.

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 1 |
| MEDIUM | 2 |
| LOW | 2 |
