# Legal and Regulatory Compliance Review — Bullpen
**Run date:** 2026-05-12  
**Reviewer role:** Technology transactions attorney / compliance counsel evaluating for acquisition

---

## Executive Summary

Bullpen is a developer tool distributed under the MIT License. Its legal exposure profile is largely favorable: it handles no personal data by default, requires no regulatory filings, and imposes clear terms on its dependencies. The primary compliance gaps are the absence of formal Terms of Service and Privacy Policy documents, missing export control acknowledgment, and the need to clarify the scope of the MIT license as applied to the bundled agent profile templates. No material blocking issues were identified.

---

## Findings

### HIGH — No Terms of Service or End User License Agreement

**Detail:** The repository contains no Terms of Service, End User License Agreement (EULA), or similar user-facing legal instrument. The MIT License in `LICENSE` governs redistribution rights for contributors and redistributors but does not establish any usage terms between Bullpen and its end users (self-hosters, commercial operators, or hosted-service subscribers). A commercial deployment or SaaS offering built on Bullpen would need explicit ToS before accepting users, particularly to:

- Disclaim warranties and limit liability (the MIT License disclaimer covers contributors but not operators)
- Prohibit use for illegal purposes
- Establish jurisdiction and dispute resolution venue
- Address acceptable use of the agent execution capability (e.g., no automation of illegal activity)

**Recommendation:** Draft a standard SaaS Terms of Service and an Acceptable Use Policy. Even for a self-hosted tool, a `NOTICE` file clarifying warranty disclaimers for operators is best practice. Priority HIGH because this gap becomes a blocker the moment any hosted or commercial offering launches.

---

### HIGH — No Privacy Policy

**Detail:** Bullpen, in its current form, processes no personal data beyond what is implicitly present in task tickets (which the operator and their agents write). However:

1. If Bullpen is offered as a hosted service (SaaS), it would collect at minimum email addresses and usage data, triggering GDPR, CCPA, and similar regimes.
2. The Docker deployment accepts `BULLPEN_BOOTSTRAP_PASSWORD` via environment variable, which constitutes processing of authentication credentials.
3. The `docs/login.md` documents a multi-user authentication system, which means the product is designed to handle multiple users' credentials.

GDPR Article 13/14 requires a privacy notice when personal data is collected. CCPA requires a privacy policy for California businesses above certain thresholds. Even for current self-hosted use, operators deploying Bullpen for teams need guidance on what data Bullpen touches.

**Recommendation:** Draft a Privacy Policy that describes what data Bullpen collects (auth credentials, ticket content, agent output), where it is stored (local filesystem only, no cloud sync by default), and how it is protected. Provide a `PRIVACY.md` in the repository for open-source transparency.

---

### MEDIUM — Export control considerations for AI agent integrations

**Detail:** Bullpen integrates with Claude Code (Anthropic), Codex CLI (OpenAI), and Gemini CLI (Google). Each of these AI systems may be subject to U.S. export control regulations (EAR, ITAR) due to their classification as dual-use technology. The Bullpen software itself is a general-purpose developer tool and likely falls under EAR99 (no license required), but documentation should acknowledge that:

1. Users in restricted countries may not be permitted to use the AI agent integrations.
2. Operators deploying Bullpen in regions subject to U.S. sanctions should verify compliance with the provider-specific terms.

**Recommendation:** Add an export control notice to `README.md` or a `LEGAL.md` file stating that use of integrated AI agents is subject to the terms and export restrictions of the respective AI providers, and that users are responsible for compliance with applicable export control laws.

---

### MEDIUM — Agent profile templates may incorporate third-party IP

**Location:** `profiles/` directory (25 JSON template files)

**Detail:** The 25 built-in worker profile templates contain prompt engineering patterns and system prompts. If any of these were derived from published research papers, commercial prompt templates, or AI provider documentation examples, there could be a copyright or IP question around their inclusion in an MIT-licensed repository. The review found no obvious copying from protected sources, but a formal IP clearance has not been performed.

**Recommendation:** Document the provenance of each profile template in a `profiles/PROVENANCE.md` file, confirming that all prompt text was authored by the project contributors or is in the public domain. If any template content was derived from third-party sources, obtain appropriate licenses or replace the content.

---

### MEDIUM — Contributor License Agreement (CLA) not established

**Detail:** The repository uses the MIT License and accepts (or will accept) contributions. Without a CLA or Developer Certificate of Origin (DCO) requirement, the project cannot be certain that contributors have the legal right to contribute the code they submit, or that the project has a clear record of IP ownership. This is a standard risk for open-source projects and becomes material at acquisition time (acquirers typically require IP chain of title).

**Recommendation:** Implement either a DCO (lightweight: contributors sign off commits with `Signed-off-by:`) or a formal CLA (heavier: contributors sign a document granting IP rights). DCO is the practical choice for a developer tool. GitHub's DCO action can automate this.

---

### LOW — MIT License header absent from source files

**Detail:** The `LICENSE` file at the repository root correctly contains the MIT License text. However, individual source files (`.py`, `.js`) do not contain SPDX license headers (`// SPDX-License-Identifier: MIT`). While not legally required for MIT, the absence of per-file headers creates ambiguity when files are extracted from the repository context (e.g., copied into another project, published as a snippet).

**Recommendation:** Add `# SPDX-License-Identifier: MIT` to the top of Python source files and `// SPDX-License-Identifier: MIT` to JavaScript files. This is a one-time mechanical change and eliminates any licensing ambiguity for downstream users.

---

### LOW — No explicit governing law or jurisdiction clause

**Detail:** Neither the MIT License nor any other repository document specifies a governing law or jurisdiction for disputes. For an open-source project, this is normal and acceptable. If the project transitions to a commercial offering or SaaS, the absence of a jurisdiction clause would need to be remedied in the ToS.

**Recommendation:** Include jurisdiction and governing law in the ToS drafted under the HIGH finding above. No immediate action required for the current open-source-only distribution model.

---

## Compliance Frameworks Assessment

| Framework | Applicability | Current Status |
|---|---|---|
| GDPR (EU) | Applies if hosted for EU users | No privacy policy; not compliant for hosted deployment |
| CCPA (California) | Applies to CA-based operators with ≥$25M revenue or ≥100K consumers | No privacy policy; risk scales with operator size |
| COPPA | N/A — not a consumer app for minors | No action needed |
| HIPAA | N/A — no health data processed | No action needed |
| SOC 2 | Would be required for enterprise SaaS | No audit trail; not ready |
| Export Control (EAR) | Low risk for software itself | Notice recommended |
| Open Source License Compliance | MIT is permissive; dependencies all compatible | See 12-license-audit.md |

---

## Severity Summary

| Severity | Count |
|---|---|
| HIGH | 2 |
| MEDIUM | 3 |
| LOW | 2 |
