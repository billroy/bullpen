# Legal and Regulatory Compliance Review — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** Legal counsel / compliance analyst evaluating as a potential acquirer

---

## Scope

Review of software licensing, terms of service, privacy notices, regulatory applicability (GDPR, CCPA, export controls), contributor agreements, and third-party dependency license obligations.

---

## Executive Summary

Bullpen has no public-facing legal infrastructure: no software license, no terms of service, no privacy notice, and no contributor license agreement. As a localhost developer tool with no external data transmission, the regulatory exposure is low in its current form. However, the complete absence of a software license is the most significant gap — it leaves the IP status of the codebase legally ambiguous and blocks any distribution or commercialization path.

---

## Findings

### HIGH — No Software License

**Location:** Repository root — no `LICENSE`, `LICENSE.md`, or `LICENSE.txt` file found.

A codebase with no license is legally "all rights reserved" by default in most jurisdictions. This has several consequences:

1. **Distribution is blocked.** No one can legally use, copy, distribute, or modify the software without explicit written permission from the author.
2. **Open-source contribution is blocked.** Contributors have no legal grant to submit code; the repository cannot be treated as an open-source project without a license.
3. **Acquirer cannot take title clearly.** A buyer needs to know what IP they are acquiring and under what terms.
4. **GitHub's Terms of Service create limited implicit rights** (e.g., viewing and forking within GitHub's platform), but these do not substitute for a proper license.

**Recommendation:** Choose a license and add it to the repository root. If the intent is to keep the software proprietary, add a brief proprietary notice. If open-source, MIT or Apache 2.0 are standard choices for developer tools.

---

### MEDIUM — No Privacy Notice or Data Handling Policy

**Location:** README.md, docs/ — no privacy policy found.

The product processes task descriptions, file contents, and agent outputs. While current deployments are localhost-only with no telemetry, users and operators have no documented statement of what data is collected, stored, or transmitted.

**Note:** In its current form (localhost, no telemetry, no accounts), Bullpen has minimal GDPR/CCPA exposure. However, if the product is ever offered as a hosted service or adds any analytics, a privacy notice becomes mandatory under GDPR (EU), CCPA (California), and similar laws.

**Recommendation:** Add a one-page `docs/privacy.md` or a section in the README stating: (a) what data is stored, (b) that no telemetry is collected, (c) that task data stays in the local workspace directory, and (d) that agent API calls are subject to the AI provider's privacy policy.

---

### MEDIUM — No Contributor License Agreement

**Location:** Repository — no CLA file or CLA bot configuration found.

If Bullpen accepts external contributions (pull requests), contributors retain copyright over their submissions unless they assign or license those rights to the project owner. Without a CLA or DCO (Developer Certificate of Origin), the project cannot cleanly transfer copyright to a buyer or change the license later.

**Recommendation:** Add a `DCO.md` and require `Signed-off-by:` in commit messages, or configure a CLA assistant. For a proprietary project, a short CLA requiring copyright assignment is standard practice.

---

### LOW — AI Provider Terms of Service Compliance

**Location:** `server/agents/claude_adapter.py`, `server/agents/codex_adapter.py`

Bullpen invokes the Claude CLI and Codex CLI as subprocesses. The operator's use of these AI services is subject to Anthropic's and OpenAI's terms of service, respectively. Key areas to verify:

- **Acceptable use:** Bullpen uses `--dangerously-skip-permissions` (Claude) and `--full-auto` (Codex). Whether these invocation modes comply with each provider's terms should be verified.
- **Data retention:** Prompts and agent outputs may be processed or stored by the AI provider per their privacy policy. Operators should be informed.

**Recommendation:** Add a note to the README/docs explaining that task prompts are sent to the configured AI provider and are subject to that provider's terms.

---

### LOW — Export Control Considerations

Bullpen uses standard open-source cryptographic libraries (Werkzeug scrypt for password hashing). Use and distribution of cryptographic software may be subject to export regulations (U.S. EAR) in some jurisdictions. The Werkzeug library is widely exported, but a formal compliance review should confirm applicability if the software is to be commercially distributed internationally.

---

### NOT APPLICABLE

- **HIPAA:** No health information processed.
- **PCI-DSS:** No payment card data handled.
- **SOC 2:** Not a hosted service at this time.
- **CCPA/GDPR enforcement:** No personal data of end users collected or stored by the operator (task data belongs to the operator themselves).

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| LEG-01 | No software license | HIGH |
| LEG-02 | No privacy notice | MEDIUM |
| LEG-03 | No contributor license agreement | MEDIUM |
| LEG-04 | AI provider ToS compliance not documented | LOW |
| LEG-05 | Export control review not performed | LOW |
