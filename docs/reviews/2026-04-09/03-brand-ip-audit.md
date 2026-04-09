# Brand and IP Audit — Bullpen
**Review date:** 2026-04-09
**Reviewer role:** IP attorney / brand strategist evaluating as a potential acquirer

---

## Scope

Audit of trademark status, brand assets, naming conflicts, intellectual property ownership, trade secret protections, and original creative expression in the codebase.

---

## Executive Summary

The "Bullpen" brand is unregistered and unprotected. There is no trademark filing, no domain acquisition documented, and no evidence of a formal IP ownership assignment. The product name carries moderate conflict risk given its common usage in sports and business contexts. The codebase contains original, non-trivial creative work (fractional indexing implementation, agent adapter abstraction, MCP integration) that represents genuine IP value, but it is currently unprotected due to the absence of a software license.

---

## Findings

### HIGH — "Bullpen" Trademark Not Registered or Searched

**Location:** README.md, repository root — no trademark notice, registration number, or ™/® symbol found.

"Bullpen" is a common English word widely used in:
- Baseball (pitcher holding area)
- Business/startup contexts (open-plan offices, startup incubators)
- Several existing software products and SaaS tools

Without a trademark search and registration, the brand carries:
1. **Conflict risk** — A prior user of "Bullpen" in a related software/AI tools category could send a cease-and-desist.
2. **Acquisition risk** — A buyer cannot acquire a brand they cannot protect. Due diligence will flag an unregistered mark.
3. **Domain risk** — No evidence that `bullpen.ai`, `bullpen.dev`, or similar domains are secured.

**Recommendation:**
1. Conduct a trademark clearance search (USPTO TESS, EUIPO, international) for "Bullpen" in IC 042 (software) and IC 045 (AI services).
2. File an intent-to-use trademark application in relevant jurisdictions if the search is clear.
3. Secure key domain names.

---

### MEDIUM — No Copyright Notices in Source Files

**Location:** All source files — no `# Copyright (c) [Year] [Owner]` header found.

Copyright attaches automatically at creation, but the absence of explicit copyright notices in source files:
1. Makes it harder to prove ownership and creation date in litigation.
2. Does not put downstream recipients on notice of the copyright claim.
3. Reduces the deterrence effect for infringement.

**Recommendation:** Add a standard copyright header to key source files (e.g., `# Copyright (c) 2025-2026 [Author/Company]. All rights reserved.`). This is a one-time, low-effort change.

---

### MEDIUM — IP Ownership Assignment Not Documented

**Location:** Repository — no employee IP assignment agreement, contractor work-for-hire agreement, or IP assignment documentation found.

If the codebase was developed by a team, contractor, or while an employee of another company, the IP ownership may not fully vest in the apparent owner. A buyer would require documentation that:
1. All contributors have assigned their IP rights.
2. No employer "moonlighting" clause applies to code written during employment.
3. No contractor retains rights to their contributions.

**Recommendation:** Execute an IP assignment agreement with all contributors and document that development did not occur under an employment agreement with conflicting IP provisions.

---

### LOW — Product Name Conflicts with Existing Tools

**Location:** README.md — product is named "Bullpen"

A search of public registries and app stores reveals "Bullpen" is used by other tools in adjacent categories (project management, team collaboration). While not necessarily in the same IC class, this creates market confusion risk and potential opposition to any trademark filing.

**Recommendation:** Consider whether a more distinctive brand name (coined word or unique compound) would better protect the product's identity.

---

### LOW — No Trade Secret Protections in Place

The novel elements of Bullpen's implementation (agent orchestration patterns, fractional indexing for task ordering, MCP tool integration for agents-as-workers) represent potentially protectable trade secrets. Without:
- Confidentiality agreements with contributors
- Access controls on the repository
- A documented trade secret policy

...these elements cannot be claimed as trade secrets in litigation.

**Recommendation:** If the repository is private, document access controls. If open-source licensing is chosen, trade secret protection is waived — ensure this is intentional.

---

### POSITIVE FINDINGS

- **Original codebase:** No copied code from other projects detected. The fractional indexing implementation, workspace manager, and agent adapter pattern are original implementations.
- **CDN dependencies are correctly attributed:** All CDN libraries are used via public CDN links with version pins and SRI hashes. No vendored code is present without attribution.
- **Profile JSON files:** The 24 built-in worker profiles are original content and represent genuine product value.

---

## Severity Summary

| ID | Finding | Severity |
|----|---------|---------|
| BRAND-01 | "Bullpen" trademark not registered or searched | HIGH |
| BRAND-02 | No copyright notices in source files | MEDIUM |
| BRAND-03 | IP ownership assignment not documented | MEDIUM |
| BRAND-04 | Product name conflicts with existing tools | LOW |
| BRAND-05 | No trade secret protections in place | LOW |
