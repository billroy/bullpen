# Brand and IP Audit — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** IP counsel and brand strategy advisor evaluating for acquisition

---

## Executive Summary

The "Bullpen" brand is evocative and domain-specific to its use case (a holding area for work items and agents, analogous to a baseball bullpen). No registered trademark conflicts were identified in this review, though a formal trademark clearance search has not been conducted. The codebase itself is original work, MIT-licensed, and free of obviously copied third-party content. The primary IP risks are: no registered trademark protection, no CLA/DCO for contributor IP chain of title, and the use of third-party agent CLI brands (Claude, Codex, Gemini) in UI and documentation in ways that require brand guideline compliance.

---

## Findings

### HIGH — No trademark registration or clearance for "Bullpen"

**Detail:** The name "Bullpen" is a common English word with broad use across industries (software, sports, finance, creative agencies). A USPTO search is required to determine whether any existing registered marks could conflict. Relevant risk areas:

1. **Software category (Class 42):** Other developer tools or SaaS products may use "Bullpen" in the software/tech services category.
2. **Domain and social handles:** No investigation of `bullpen.com`, `getbullpen.com`, or social media handle availability was conducted as part of this review.
3. **International marks:** If the product is distributed globally, EU (EUIPO) and UK (IPO) searches are also needed.

An unregistered mark provides common-law protection only in geographies where the product is actively used, which is insufficient protection for a commercial product.

**Recommendation:** Commission a trademark clearance search (USPTO, EUIPO, and relevant national registries) before any commercial launch. If the search is clear, file for registration in Class 42 (Computer programming, software as a service) in the U.S. and key international markets. Establish a trademark watch service to monitor future conflicts.

---

### MEDIUM — Use of AI provider brand names in UI and marketing-adjacent documentation

**Location:** `static/` (UI displays "Claude", "Codex", "Gemini" as agent type labels), `README.md`, `docs/` (provider names throughout)

**Detail:** Bullpen prominently features the trademarks of Anthropic (Claude), OpenAI (Codex), and Google (Gemini) in its user interface and documentation. Each provider has trademark and brand guidelines:

- **Anthropic / Claude:** Anthropic's usage guidelines require that third-party apps not imply official partnership or endorsement; the name "Claude" may be used to describe compatibility, but not as a feature name implying ownership.
- **OpenAI / Codex:** OpenAI's brand policy similarly restricts use of "GPT", "Codex", and "OpenAI" in product names and requires a disclaimer for third-party integrations.
- **Google / Gemini:** Google's brand terms restrict use of "Gemini" in ways that could imply Google sponsorship.

The current UI use (labeling agent types as "claude", "codex", "gemini") is descriptive and likely falls within acceptable nominative fair use. However, there is no disclaimer on the product page, repository, or documentation stating that Bullpen is an independent project not affiliated with or endorsed by Anthropic, OpenAI, or Google.

**Recommendation:** Add a standard disclaimer to `README.md` and any product marketing: "Bullpen is an independent project not affiliated with, endorsed by, or sponsored by Anthropic, OpenAI, or Google. Claude, Codex, and Gemini are trademarks of their respective owners." Review each provider's current brand guidelines before commercial launch.

---

### MEDIUM — No Contributor License Agreement; IP chain of title is informal

**Detail:** (Cross-references `02-legal-compliance.md`) The repository does not use a CLA or DCO. For IP purposes, this means:

1. There is no documented record that contributors transferred or licensed their IP to the project.
2. Under U.S. copyright law, each contributor retains copyright in their contributions by default. The MIT License governs downstream distribution, but the project itself does not have a clean "all IP is licensed to the project maintainer" chain.
3. At acquisition, a buyer's IP diligence team will request evidence of contributor agreements. The absence of a CLA or DCO creates a gap that must be remediated or disclosed.

**Recommendation:** Implement DCO (Developer Certificate of Origin 1.1) retroactively by asking existing contributors to sign off, and require it for all future contributions. A DCO is lighter-weight than a CLA while still providing a documented IP representation from each contributor.

---

### LOW — No copyright notice in individual source files

**Detail:** Source files lack per-file copyright headers (e.g., `# Copyright 2026 Bullpen Contributors`). The `LICENSE` file establishes copyright at the repository level, but per-file headers are standard practice for commercial open-source projects and are expected by acquirers during IP diligence.

**Recommendation:** Add `# Copyright 2026 Bullpen Contributors` and `# SPDX-License-Identifier: MIT` headers to all Python and JavaScript source files. A one-time script can perform this addition.

---

### LOW — ASCII art (pyfiglet) renders "BULLPEN" at startup

**Location:** `bullpen.py` (startup banner using pyfiglet)

**Detail:** The pyfiglet library renders ASCII art from bundled font files. pyfiglet is MIT-licensed, but the underlying fonts included in pyfiglet may have their own licenses (some are FIGlet fonts with custom licenses permitting free use with attribution). No font attribution issue is expected, but this should be verified against the pyfiglet license manifest.

**Recommendation:** Verify that the specific pyfiglet font used in the Bullpen banner is cleared for commercial use. This is a low-effort verification (check pyfiglet's `LICENSE` and font metadata).

---

### LOW — Profile template names reference external methodologies

**Location:** `profiles/` directory (25 JSON template files)

**Detail:** Some profile template names and descriptions reference general software methodologies (e.g., "code review", "security audit", "refactor"). These are generic terms and do not constitute trademark or IP issues. However, if any profile names reference proprietary methodologies (e.g., named frameworks, consulting methodologies), those references should be reviewed.

**Recommendation:** Review profile template names and descriptions for any references to proprietary named methodologies or frameworks. No action required if all references are to generic software engineering practices.

---

## Positive IP Controls (No Action Required)

| Control | Status |
|---|---|
| MIT License at repository root | Correct and complete |
| No GPL/copyleft dependencies in core | Verified (all deps MIT/BSD) |
| SRI hashes on CDN assets | Prevents supply-chain substitution |
| Original codebase (no evidence of copying) | No copied code identified |
| Agent CLI integrations via official APIs | Correct use of provider-sanctioned integration points |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 1 |
| MEDIUM | 2 |
| LOW | 3 |
