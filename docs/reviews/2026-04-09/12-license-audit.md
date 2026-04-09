# Third-Party & Open-Source License Audit — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** Open-source compliance attorney / license auditor evaluating as a potential acquirer

---

## Scope

Full inventory of all third-party software components — backend Python packages, frontend CDN libraries, and transitive dependencies — with license identification, obligation analysis, compatibility assessment, and compliance gap findings.

---

## Executive Summary

Bullpen uses a small, clean dependency set. Every identified third-party component carries a permissive license (MIT or BSD-3-Clause). There are no copyleft (GPL/LGPL/AGPL) dependencies that would impose reciprocal obligations on the codebase. The primary compliance gaps are: (1) the absence of a project-level LICENSE file, (2) no NOTICE or THIRD_PARTY_NOTICES file crediting upstream components, (3) unpinned dependency versions which prevent auditability of the exact component set in production, and (4) the deprecated `eventlet` dependency which is in bugfix-only mode and carries maintenance risk. Overall, the license posture is clean and acquisition-ready once the documentation gaps are closed.

---

## Dependency Inventory

### Backend — Python (from `requirements.txt` + transitive)

| Package | License | Version Pinned | Notes |
|---------|---------|----------------|-------|
| Flask | BSD-3-Clause | No (unpinned) | Widely used; permissive |
| Flask-SocketIO | MIT | Partial (>=5.3.6) | Permissive |
| Werkzeug | BSD-3-Clause | No (transitive via Flask) | Ships with Flask |
| python-socketio | MIT | No (transitive) | Core SocketIO server |
| python-engineio | MIT | No (transitive) | Core EngineIO server |
| eventlet | MIT | No (unpinned) | **DEPRECATED** by maintainers; bugfix-only since 2023 |
| pytest | MIT | No (unpinned) | Dev dependency only; not distributed |
| greenlet | MIT | No (transitive via eventlet) | CPython C extension |
| dnspython | ISC | No (transitive via eventlet) | ISC is functionally equivalent to MIT |
| six | MIT | No (transitive) | Python 2/3 compat shim |

**Note on Werkzeug:** Used directly for `check_password_hash` / `generate_password_hash` in `server/auth.py`. BSD-3-Clause requires preserving copyright notice and the BSD disclaimer in documentation/distributions.

### Frontend — CDN Libraries (from `static/index.html`)

All frontend dependencies are loaded from public CDNs with Subresource Integrity (SRI) hashes. Version pinning is present at the CDN URL level.

| Library | Version | License | SRI Present | CDN |
|---------|---------|---------|-------------|-----|
| Vue.js 3 | latest (unpkg) | MIT | No | unpkg.com |
| Socket.IO Client | 4.7.5 | MIT | Yes (sha384) | cdn.socket.io |
| markdown-it | 13.0.2 | MIT | Yes (sha384) | cdnjs.cloudflare.com |
| Prism.js (core + 6 langs) | 1.29.0 | MIT | Yes (sha384) | cdnjs.cloudflare.com |
| Prism.js CSS theme | 1.29.0 | MIT | Yes (sha384) | cdnjs.cloudflare.com |

**Vue.js SRI gap:** The Vue 3 script loaded from `unpkg.com/vue@3/...` (floating `@3` tag, not a pinned version) does not have an `integrity` attribute. All other CDN resources have SRI hashes. This is inconsistent and creates both a supply-chain risk and a license auditability gap (the exact version in production is not deterministic).

---

## License Obligations Analysis

### BSD-3-Clause (Flask, Werkzeug)

BSD-3-Clause requires:
1. Retain copyright notice in source distributions.
2. Retain license text in binary distributions.
3. Do not use the licensor's name in advertising without permission.

**Current compliance:** If Bullpen is distributed (packaged, containerized, or sold), these notices must appear in accompanying documentation or a NOTICE file. No NOTICE file currently exists.

### MIT (Flask-SocketIO, eventlet, Vue.js, Socket.IO, markdown-it, Prism.js, et al.)

MIT requires:
1. Include the copyright notice and permission notice in all copies or substantial portions of the software.

**Current compliance:** Same gap — no NOTICE file or THIRD_PARTY_NOTICES file listing MIT copyright holders.

### ISC (dnspython via eventlet)

ISC is functionally identical to MIT. Same obligations apply.

### No Copyleft Dependencies

No GPL, LGPL, AGPL, MPL, or EUPL components were identified. There are no reciprocal licensing obligations that would require releasing Bullpen's source code.

---

## Findings

### HIGH — No Project LICENSE File

**Location:** Repository root — no `LICENSE`, `LICENSE.md`, or `LICENSE.txt` found.

Without a project license:
1. The default legal status is "all rights reserved." Nobody can legally use, copy, or distribute the software.
2. Open-source upstream authors retain their rights with no clear grant to the project owner for combination or modification.
3. An acquirer cannot determine what they are buying or what rights they receive.

**Recommendation:** Add a `LICENSE` file. If open-source, MIT is consistent with all upstream licenses. If proprietary, add a proprietary notice.

---

### MEDIUM — No NOTICE / THIRD_PARTY_NOTICES File

**Location:** Repository root — no `NOTICE`, `THIRD_PARTY_NOTICES.md`, or equivalent file found.

BSD-3-Clause (Flask, Werkzeug) and MIT licenses require that copyright notices be preserved in distributions. Without a NOTICE file, a binary or packaged distribution of Bullpen would be out of compliance with the upstream license terms.

**Recommendation:** Create `THIRD_PARTY_NOTICES.md` listing each component, its version, its license, and the upstream copyright notice. This is a one-time, low-effort compliance step.

---

### MEDIUM — Vue.js CDN Tag Is Not Version-Pinned (No SRI)

**Location:** `static/index.html` — Vue 3 script tag

```html
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
```

No `integrity` attribute is present, and `@3` resolves to whatever the latest Vue 3.x release is at load time. This means:
1. The exact Vue version in production is not auditable — a compliance reviewer cannot confirm which version (and thus which license text) is in use.
2. A compromised or altered unpkg delivery would not be detected (contrast: all other CDN dependencies have SRI hashes).

**Recommendation:** Pin to a specific version (e.g., `@3.5.13`) and add an `integrity` SRI hash. This resolves both the license auditability gap and the supply-chain risk flagged in the security audit.

---

### MEDIUM — `eventlet` Is Deprecated; No Actively Maintained Alternative in Place

**Location:** `requirements.txt`, `server/app.py`

`eventlet` is listed as a dependency and is in the requirements. The eventlet maintainers have announced the library is in bugfix-only mode (no new features, no active development). This creates:
1. **Future CVE risk:** Security vulnerabilities may not be patched in a timely manner.
2. **Compatibility risk:** Python 3.13+ may break eventlet without a fix being available.
3. **License continuity risk:** If eventlet is eventually abandoned, the version in production may not receive license-related updates.

**Note:** The application appears to use `async_mode="threading"` (not eventlet greenlets), so eventlet may be an unnecessary dependency. Verification is recommended.

**Recommendation:** Audit whether eventlet is actually needed (check `async_mode` in `server/app.py`). If not, remove it from `requirements.txt`. If needed, evaluate migrating to `gevent` (MIT, actively maintained) or pure threading mode without eventlet.

---

### LOW — No Dependency Pinning Prevents License Audit Reproducibility

**Location:** `requirements.txt`

With unpinned dependencies (`flask`, `eventlet`, `pytest`), a `pip install -r requirements.txt` at different times may produce different package versions with potentially different license terms (though in practice, all identified packages have stable permissive licenses that do not change between minor versions).

**Recommendation:** Pin all dependencies to exact versions in a `requirements.lock` (generated by `pip-compile`). This ensures any license audit is reproducible and verifiable against a known component set.

---

### LOW — No Automated License Scanning in CI

**Location:** Repository root — no license-check tooling configured.

There is no `pip-licenses`, `license-check`, Dependabot, or equivalent tool scanning for license changes or new dependencies with non-permissive licenses. A future contributor adding a GPL dependency would not be caught automatically.

**Recommendation:** Add `pip-licenses` to the CI pipeline (once CI is established per the operational review). Fail the build if any dependency with a non-permissive license (GPL, AGPL, etc.) appears.

---

### POSITIVE FINDINGS

- **No copyleft dependencies:** All identified licenses are permissive (MIT, BSD-3-Clause, ISC). No reciprocal licensing obligations exist.
- **SRI hashes on 9 of 10 CDN resources:** Correct supply-chain integrity practice for all CDN dependencies except Vue.js.
- **No vendored code:** No third-party source code has been copied into the repository without attribution.
- **No dual-licensed or "Commons Clause" components:** All dependencies use standard, unambiguous open-source licenses.
- **Dev-only dependencies isolated:** `pytest` is in `requirements.txt` but clearly a dev dependency. It is MIT-licensed and does not affect the runtime license posture.

---

## License Compatibility Matrix

| Component | License | Compatible with MIT project release? | Compatible with proprietary release? |
|-----------|---------|--------------------------------------|--------------------------------------|
| Flask | BSD-3-Clause | Yes (with notice) | Yes (with notice) |
| Werkzeug | BSD-3-Clause | Yes (with notice) | Yes (with notice) |
| Flask-SocketIO | MIT | Yes | Yes (with notice) |
| eventlet | MIT | Yes | Yes (with notice) |
| Vue.js 3 | MIT | Yes | Yes (with notice) |
| Socket.IO Client | MIT | Yes | Yes (with notice) |
| markdown-it | MIT | Yes | Yes (with notice) |
| Prism.js | MIT | Yes | Yes (with notice) |

**Summary:** All dependencies are compatible with both an open-source (MIT) and a proprietary release of Bullpen, provided copyright notices are preserved in a NOTICE file.

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| LIC-01 | No project LICENSE file | HIGH |
| LIC-02 | No NOTICE / THIRD_PARTY_NOTICES file | MEDIUM |
| LIC-03 | Vue.js CDN not version-pinned, no SRI hash | MEDIUM |
| LIC-04 | `eventlet` deprecated; maintenance risk | MEDIUM |
| LIC-05 | No dependency pinning prevents audit reproducibility | LOW |
| LIC-06 | No automated license scanning in CI | LOW |
