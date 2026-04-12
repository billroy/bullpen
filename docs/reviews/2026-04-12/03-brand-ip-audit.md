# Brand and IP Audit — Bullpen
Run date: 2026-04-12 | Output folder: docs/reviews/2026-04-12

---

## Scope

Review of trademark usage, third-party brand references, intellectual property claims, and any potential infringement or brand risk in the codebase and product materials.

---

## Findings

### HIGH — No LICENSE file or copyright notice

**Files:** All source files; repository root

No source file contains a copyright header. No `LICENSE` file exists at the repository root. If the project is distributed publicly, this creates ambiguity about ownership and rights. Standard practice is to add a `Copyright (c) <year> <owner>` notice to a `LICENSE` file and optionally to file headers.

**Recommendation:** Add a `LICENSE` file with an explicit copyright owner and year. Consider adding a `# Copyright (c) 2026 <owner>` header to `bullpen.py` and top-level modules.

---

### MEDIUM — Product name "Bullpen" not searched for existing trademark

**Files:** `README.md`, `bullpen.py`, all static assets

The product is named "Bullpen." The name is used consistently across the codebase, README, and UI. There is no evidence of a trademark search having been performed. "Bullpen" is a common English word and a term used in several existing software products (e.g., creative agency and staffing platforms). If this product is to be distributed commercially or publicly under the Bullpen name, a trademark clearance search should be performed.

**Recommendation:** Perform a USPTO/EUIPO trademark search for "Bullpen" in the relevant software/SaaS class (Class 42) before commercial launch.

---

### MEDIUM — Third-party AI provider names used as agent identifiers

**Files:** `server/validation.py:17`, `server/agents/__init__.py`, `static/app.js`, multiple frontend components

The codebase uses "claude", "codex", and "gemini" as string constants for agent type selection throughout the system. These are references to:
- **Claude** — a registered trademark of Anthropic, PBC
- **Codex** — an OpenAI product name
- **Gemini** — a registered trademark of Google LLC

Usage as internal identifiers in a developer tool (rather than marketing claims) is generally permissible under nominative fair use. However:
- The product is not affiliated with or endorsed by Anthropic, Google, or OpenAI.
- No disclaimer to this effect appears in the README or UI.

**Recommendation:** Add a brief disclaimer to the README: "Bullpen is not affiliated with or endorsed by Anthropic, Google, or OpenAI. Claude, Gemini, and Codex are trademarks of their respective owners."

---

### LOW — Built-in profiles reference third-party product names

**Files:** `profiles/` directory (24 JSON profile files including `code-reviewer.json`, `feature-architect.json`, etc.)

The built-in agent profiles are bundled with the project. They do not reference third-party trademarks directly. However, if profiles are contributed by third parties in the future, a contribution policy should specify that contributed content cannot contain trademarked names or copyrighted content without permission.

---

### LOW — No NOTICE or ATTRIBUTION file for dependencies

**Files:** Repository root

Open-source dependencies (Flask, Werkzeug, Flask-SocketIO, eventlet, etc.) have their own copyright notices and attribution requirements (typically satisfied by including their license texts). No `NOTICE` or `ATTRIBUTIONS` file exists. For Apache 2.0 dependencies (if any are added), a `NOTICE` file may be legally required.

**Recommendation:** When a LICENSE file is added, include or reference the licenses of bundled or distributed dependencies.

---

### LOW — Frontend loads external CDN assets without version pinning for some

**File:** `static/index.html`

The frontend loads Vue 3, Socket.IO client, Markdown-It, and Prism from CDN URLs. If CDN assets are not pinned to exact versions with SRI hashes, CDN-served JavaScript could be silently updated. A review of `index.html` should confirm all CDN scripts include `integrity` attributes with SHA hashes.

*Note: The agent summary of index.html mentions "All JavaScript dependencies are loaded from CDNs with integrity checks" — this will be verified in the accessibility and security reviews.*

---

## Positive Observations

- The product name "Bullpen" does not directly copy or imitate any competitor product's name.
- No copyrighted code or assets (images, fonts, icon sets) are bundled without attribution.
- The 24 built-in worker profiles are original content.

---

## Severity Summary

| ID | Severity | Finding |
|----|----------|---------|
| B1 | HIGH | No LICENSE file or copyright notice |
| B2 | MEDIUM | "Bullpen" product name not trademark-searched |
| B3 | MEDIUM | Third-party AI provider trademarks used without disclaimer |
| B4 | LOW | No contribution policy for profile submissions |
| B5 | LOW | No NOTICE/ATTRIBUTION file for dependencies |
| B6 | LOW | CDN SRI hashes need verification |
