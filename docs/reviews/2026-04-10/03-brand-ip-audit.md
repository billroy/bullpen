# Brand and IP Audit — Bullpen
**Review date:** 2026-04-10  
**Reviewer role:** Brand / IP Analyst  
**Perspective:** Potential acquirer / independent assessment

---

## Executive Summary

The "Bullpen" brand is unregistered and the name is in wide use across unrelated industries (baseball, HR software, finance). No trademark search was performed, but the generic nature of the term creates risk for any commercial launch. The codebase contains no IP-infringing assets and no embedded third-party brand elements beyond properly-licensed icon and UI libraries.

---

## Severity Table

| ID | Severity | Finding |
|----|----------|---------|
| B1 | MEDIUM | "Bullpen" is a common dictionary word — trademark registrability is low without acquired distinctiveness |
| B2 | MEDIUM | No LICENSE file means IP ownership is legally ambiguous (see L1 in legal review) |
| B3 | LOW | AI-generated code (Claude Code) — ownership of AI outputs may vary by jurisdiction and Anthropic ToS |
| B4 | LOW | No registered trademark, domain registration status unknown |
| B5 | INFO | No favicon/logo assets found that could create trademark or copyright issues |
| B6 | INFO | Profile names (e.g., "feature-architect", "security-reviewer") are descriptive, not distinctive |

---

## Detailed Findings

### B1 — MEDIUM: Brand name genericness

"Bullpen" is a common English term used extensively in:
- Baseball (the relief pitcher area)
- HR and recruiting software (multiple existing products)
- Finance (analyst training rooms at investment banks)

A trademark search (USPTO TESS, EUIPO, national registries) should be conducted before any commercial release or acquisition to determine whether the name is available in the relevant goods/services class (likely IC 42 — software as a service).

**Risk:** A third party may hold a registered "Bullpen" trademark in the software/SaaS category, creating infringement exposure.

---

### B2 — MEDIUM: No LICENSE file — IP ownership ambiguous

Without a LICENSE file, copyright ownership defaults to the author(s) under the Berne Convention, but without explicit terms there is no documented assignment to the owning entity. An acquirer cannot receive a clean IP transfer without tracing all contributors and obtaining assignments.

See L1 in the legal compliance review for full details.

---

### B3 — LOW: AI-generated code ownership

Commits throughout the git history are co-authored by Claude Code (`Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`). Under current US copyright law, AI-generated content lacks copyright protection (Thaler v. Vidal, 2023). However:

- Code substantially directed and curated by a human author is copyrightable to that human.
- Anthropic's Claude Code usage terms grant the operator rights to outputs but this should be explicitly verified with current Anthropic ToS before an IP transfer.

**Practical risk is LOW** for a heavily human-directed codebase, but an acquirer may require a legal opinion.

---

### B4 — LOW: No registered trademark or documented domain

No trademark registration was found in the repository. The domain ownership and registration status of any bullpen-branded web presence was not assessed. An acquirer should verify:
- Domain ownership (who controls bullpen.* domains)
- Whether any trademark applications are pending or registered

---

### B5 — INFO: No custom logo or favicon assets

The `static/` directory contains no `.png`, `.ico`, `.svg`, or image files beyond what CDN libraries provide. The page title is "Bullpen" (text). No custom brand assets exist that could create copyright or trademark complications.

---

### B6 — INFO: Profile names are descriptive

The 24 built-in worker profiles (`feature-architect`, `code-reviewer`, `security-reviewer`, etc.) use descriptive industry-standard role names. None appear to reference third-party brands or proprietary methodologies. No IP issues here.

---

## Positive Controls

- All CDN libraries are properly licensed (MIT/ISC) and carry correct SRI integrity hashes (with one exception noted in the security review).
- Lucide icons are ISC-licensed — free for commercial use.
- No trademarked logos, icons, or brand assets of third parties are embedded.
- No use of GPL-licensed code that would trigger copyleft obligations.
- The codebase does not reference, embed, or redistribute Anthropic model weights or proprietary API schemas.
