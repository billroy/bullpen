# Brand & IP Audit
*Bullpen — 2026-04-27*

## Executive Summary

Bullpen is a sole-author, MIT-licensed project with no formal IP housekeeping: no
registered trademarks, no explicit copyright notice in source files, no Contributor
License Agreement, and no NOTICE file. For an acquirer this means the chain of
title is thin but clean — there is one author to contract with and no third-party
contributor claims to untangle. The primary risks are (1) the use of third-party
AI provider trademarks (Anthropic/Claude, OpenAI/Codex, Google/Gemini) in product
UI and documentation without a formal trademark policy, (2) the absence of any
brand protection for the "Bullpen" name, and (3) uncertainty about the Terms of
Service implications of wrapping commercial AI CLIs inside a commercial product.

Overall brand/IP risk: **MEDIUM**. No blockers to acquisition, but several items
require remediation before a commercial launch.

---

## Brand Assessment

### Product Name
"Bullpen" is a common English word (sports/newsroom origin). It is not inherently
distinctive as a software trademark, which makes registration possible but harder
to defend against later users of the same word in adjacent software categories.

A USPTO search is recommended prior to any commercial launch. As of the audit date
no registered software trademark for "Bullpen" in International Class 42 (software
as a service) is documented in the codebase materials, and the seller has not
represented that one exists.

### Domain Considerations
The codebase does not document which domain(s) are owned. A buyer should confirm
ownership of `bullpen.ai`, `bullpen.dev`, or equivalent before closing. Domain
squatters frequently target acquired project names post-announcement.

### Visual Identity
No custom logo, wordmark, or brand guidelines are present in the repository. The
UI uses Lucide icons (ISC-licensed) for all iconography, which is a positive: no
proprietary vendor artwork is bundled.

### Deployment Naming
The Fly.io deployment script (`deploy-sprite.sh`) references a "Sprite" product
name. If "Sprite" is a distinct sub-brand or a third-party service name (Fly.io
has used this term internally), the acquirer should confirm whether any usage
restrictions apply.

---

## IP Ownership

### Copyright
No explicit copyright notice appears in the source files or the README. The MIT
license text in `LICENSE.md` contains a placeholder (`Copyright (c) [year]
[author]`) that may not have been filled in. This creates a technical ambiguity:
the MIT license is present but the copyright holder is unnamed.

**Remediation**: Before or at closing, the seller should execute an IP assignment
agreement covering all code, documentation, and associated materials, and the
buyer should insert a proper copyright notice (`Copyright (c) 2024-2026 [Seller
Legal Name]`) into `LICENSE.md` and a representative set of source files.

### Authorship
Git history analysis indicates a single author ("bill", email bill@bitlash.net).
No `CONTRIBUTORS` file exists. This simplifies acquisition: there are no
third-party contributor claims to resolve. However, the buyer should obtain a
written warranty from the seller that no work-for-hire, employer ownership, or
contractor agreement transfers title of any portion of the code to a third party.

### CLA Status
No Contributor License Agreement process is in place. Because the project appears
to be sole-authored this is not a current problem, but post-acquisition any open-
source contribution model should include a CLA before external PRs are accepted.

### NOTICE File
No `NOTICE` file is present. Several dependency licenses (notably LGPL-2.1 for
`websocket-client`) and best practice for MIT projects require attribution in
distributed products. This is a compliance gap, not an ownership gap.

---

## Third-Party IP Risks

### AI Provider Trademarks
The codebase references three major AI provider brands by name and associates
specific brand colors with them in the UI:

| Provider | Trademark Owner | Usage in Codebase |
|----------|----------------|-------------------|
| Claude   | Anthropic, PBC  | CLI invocation, UI label, hex color #da7756 |
| Codex    | OpenAI, Inc.    | CLI invocation, UI label, hex color #5b6fd6 |
| Gemini   | Google LLC      | CLI invocation, UI label, hex color #3c7bf4 |

Using a company's brand color as an identifier in a commercial product is a gray
area. It is not trademark infringement per se, but it could be challenged as
creating a false impression of affiliation or endorsement. Each provider's
trademark guidelines (Anthropic Brand Guidelines, OpenAI Usage Policies, Google
Brand Resource Center) should be reviewed by counsel before commercial launch.

### No Vendor Logos
Lucide icons are used throughout — no official Anthropic, OpenAI, or Google logos
or icons are bundled. This is a positive finding that reduces trademark exposure.

### "Claude Code" Name
The product integrates Anthropic's `claude-code` CLI by name. Anthropic's brand
guidelines govern how third parties may refer to their products. A commercial
product that wraps or depends on `claude-code` may need a reseller or integration
agreement with Anthropic, or at minimum must comply with their acceptable use
policy for the CLI.

### Worker Profile Names
The 25 built-in worker profile templates (e.g., `code-reviewer`,
`backend-developer`) use generic job-function names. No third-party brand names
appear in profile identifiers — low risk.

---

## AI Provider Terms of Service Considerations

This section addresses whether Bullpen's business model — orchestrating commercial
AI CLIs to perform work on behalf of paying customers — is permissible under each
provider's current terms.

### Anthropic (Claude / claude-code)
Anthropic's usage policies permit third-party applications that call Claude via the
API or CLI. However, policies restrict certain automation patterns and require that
users not misrepresent the nature of AI-generated output. An acquirer building a
SaaS product on top of `claude-code` should:
- Confirm whether `claude-code` CLI usage is covered under the standard API ToS or
  requires a separate commercial agreement.
- Ensure end-user disclosures comply with Anthropic's transparency requirements.
- Monitor for changes: Anthropic's ToS and usage policies evolve rapidly.

### OpenAI (Codex / codex CLI)
The `@openai/codex` CLI is a proprietary OpenAI product. Wrapping it in a
commercial product sold to third parties may require an enterprise agreement with
OpenAI. The standard API ToS generally permits building products on the API but
may have restrictions on reselling access without disclosure.

### Google (Gemini / gemini-cli)
The `@google/gemini-cli` is subject to Google's Gemini API Terms of Service.
Similar considerations apply: commercial redistribution or resale of access
typically requires a partner agreement.

### General Risk
All three providers reserve the right to modify their CLIs, deprecate them, or
change pricing/access terms on short notice. A product whose core functionality
depends on three separate proprietary CLIs carries meaningful operational and legal
continuity risk. An acquirer should assess whether direct API integration (vs. CLI
subprocess invocation) would provide more stable contractual footing.

---

## Findings

### HIGH — Unnamed Copyright Holder in LICENSE.md

The MIT `LICENSE.md` does not name a copyright holder or year. The legal owner of
the IP is therefore not formally documented in the project artifacts. While the git
history supports a single-author presumption, any litigation or licensing dispute
would require extrinsic evidence to establish ownership. The buyer receives no
clean chain of title on the face of the license file alone.

**Remediation**: Execute an IP assignment agreement at closing. Amend `LICENSE.md`
to read `Copyright (c) 2024-2026 [Seller Legal Name]. All rights reserved.`

---

### HIGH — Unverified Compliance with AI Provider ToS for Commercial Wrapping

Bullpen's core value proposition is orchestrating `claude-code`, `codex`, and
`gemini-cli` as managed workers. None of the three provider agreements has been
reviewed or cited in the codebase or documentation. A commercial SaaS built on
this model without explicit provider authorization carries legal risk that the
provider could disable CLI access, demand royalties, or sue for breach of ToS.

**Remediation**: Before commercial launch, obtain written confirmation (or a
reseller/partner agreement) from Anthropic, OpenAI, and Google that the intended
use is permitted.

---

### MEDIUM — "Bullpen" Trademark Not Registered

The product name is unregistered and unprotected. A competitor could register
"Bullpen" in Class 42 and force a rebrand post-acquisition.

**Remediation**: File a USPTO trademark application in International Class 42
promptly after acquisition. Conduct a clearance search first.

---

### MEDIUM — No Written Warranty of Clear Title from Seller

No employment agreements, contractor agreements, or work-for-hire disclosures have
been reviewed. If the seller developed any portion of this software during
employment or under contract, the employer or client may have a colorable ownership
claim.

**Remediation**: Require seller to represent and warrant in the purchase agreement
that no third party has any claim to the IP, and to provide indemnification for any
such claims.

---

### MEDIUM — AI Provider Trademark Usage Without Policy Review

Brand colors and names for Claude, Codex, and Gemini appear in the product UI.
Each provider has trademark guidelines that may restrict how their names and brand
elements are displayed in third-party commercial products.

**Remediation**: Have counsel review each provider's trademark guidelines and
adjust UI labeling and color usage accordingly. Consider generic labels ("AI
Provider A/B/C" with user-configurable display names) as a lower-risk alternative.

---

### LOW — No NOTICE File for Attribution

Some dependency licenses (LGPL-2.1, MIT) call for preservation of copyright notices
in distributed products. The absence of a `NOTICE` or `ATTRIBUTIONS` file means
the product is not fully compliant with the attribution clauses of its dependencies.

**Remediation**: Generate a `NOTICE` file (tools like `pip-licenses` or `license-
checker` can automate this) and include it in any distribution or Docker image.

---

### LOW — No CLA for Future Contributions

If the acquirer open-sources or accepts community contributions post-acquisition,
the absence of a CLA means contributors retain copyright in their patches, complicating
future re-licensing or commercialization.

**Remediation**: Implement a CLA (e.g., via CLA Assistant) before opening the
repository to external contributions.

---

### LOW — "Sprite" Sub-brand / Deployment Name

`deploy-sprite.sh` references "Sprite." If this is a Fly.io internal product name
rather than a Bullpen-coined term, using it publicly could cause confusion or
conflict with Fly.io's branding.

**Remediation**: Confirm with Fly.io whether "Sprite" is a public product name
subject to trademark protection, and rename the deployment type to a neutral term
if so.

---

### LOW — Domain Ownership Not Confirmed

No canonical domain is documented. The buyer should confirm and acquire relevant
domains before the acquisition is announced publicly.

**Remediation**: Confirm which domain(s) the seller owns and transfer them as part
of the transaction. Register defensive variants.

---

## Severity Summary Table

| Severity | Count |
|----------|-------|
| HIGH     | 2     |
| MEDIUM   | 3     |
| LOW      | 4     |

---

## Recommendations

1. **Execute a comprehensive IP assignment agreement** at closing, with seller
   representations and warranties covering sole authorship, no work-for-hire
   encumbrances, and no third-party claims. This is the single most important step.

2. **Amend `LICENSE.md`** to name the copyright holder and year before or
   immediately after close.

3. **Engage AI provider legal/partnership teams** (Anthropic, OpenAI, Google)
   before commercial launch to confirm the CLI-wrapping model is permissible. This
   de-risks the core business.

4. **File a trademark application** for "Bullpen" in Class 42 promptly after
   acquisition. Budget for a clearance search first.

5. **Generate a `NOTICE` file** listing all dependency attributions to achieve
   license compliance.

6. **Review provider trademark guidelines** for Claude, Codex, and Gemini, and
   adjust UI brand element usage to comply.

7. **Confirm domain ownership** and transfer domains as part of the transaction.
   Register defensive variants immediately post-announcement.

8. **Institute a CLA process** before accepting any community contributions
   post-acquisition.
