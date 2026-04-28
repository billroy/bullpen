# Third-Party & Open-Source License Audit
*Bullpen — 2026-04-27*

## Executive Summary

Bullpen's dependency footprint is small and composed almost entirely of permissive
licenses (MIT, BSD-3-Clause, ISC). The one notable exception is `websocket-client`,
which carries a dual LGPL-2.1 / Apache-2.0 license; the LGPL path requires
attention depending on how the product is distributed. The higher-risk items are
the three proprietary AI CLI tools (`claude-code`, `codex`, `gemini-cli`) bundled
in the Docker image — these are commercial products whose redistribution and
embedded use in a paid SaaS may require explicit vendor authorization that is not
currently documented.

No copyleft licenses that would "infect" the Bullpen source code (GPL-2.0,
GPL-3.0, AGPL-3.0) are present in the dependency graph as reviewed. All CDN
frontend dependencies are MIT or ISC. Overall open-source license risk is
**LOW-MEDIUM**, contingent on resolving the LGPL-2.1 and proprietary CLI
questions.

---

## License Inventory

### Python Dependencies

| Package | Version | License | Notes | Compatibility |
|---------|---------|---------|-------|--------------|
| Flask | 3.1.3 | BSD-3-Clause | Permissive | Compatible |
| Flask-SocketIO | 5.6.1 | MIT | Permissive | Compatible |
| simple-websocket | 1.1.0 | MIT | Permissive | Compatible |
| websocket-client | 1.9.0 | LGPL-2.1 OR Apache-2.0 | Dual-licensed; see note | Conditional — see Finding MEDIUM-1 |
| eventlet | 0.41.0 | MIT | Permissive | Compatible |
| pytest | 9.0.3 | MIT | Dev/test only; not shipped | Compatible |

**websocket-client note**: The package declares a dual license of LGPL-2.1 or
Apache-2.0, meaning a downstream consumer may elect either. If the Apache-2.0 path
is elected the obligation is minimal (preserve notices). If the LGPL-2.1 path
applies, the acquirer must ensure end-users can replace the library without
re-linking the whole application — straightforward for a server-side Python
dependency loaded via `pip`, but must be documented and must not be statically
compiled or bundled into a binary distribution without providing object files.
The recommended posture is to explicitly elect Apache-2.0 in the project's NOTICE
file.

---

### Frontend Dependencies (CDN, loaded via `<script>` with SRI hashes)

| Library | Version | License | Notes | Compatibility |
|---------|---------|---------|-------|--------------|
| Vue | 3.5.33 | MIT | Core UI framework | Compatible |
| Socket.IO (client) | 4.7.5 | MIT | Real-time transport | Compatible |
| markdown-it | (CDN) | MIT | Markdown rendering | Compatible |
| Prism.js | (CDN) | MIT | Syntax highlighting | Compatible |
| Lucide (icons) | (CDN) | ISC | ISC is functionally equivalent to MIT | Compatible |

All CDN dependencies are loaded with SRI (Subresource Integrity) hashes, which is
a positive security posture. All are permissively licensed with no redistribution
obligations beyond attribution. Because these are loaded from a CDN at runtime
rather than bundled, no binary redistribution obligations arise.

---

### CLI Tools (Docker Runtime)

These tools are installed into the Docker image at build time and are available to
the Bullpen server as subprocess targets.

| Tool | Publisher | License | Risk Level |
|------|-----------|---------|------------|
| @anthropic-ai/claude-code | Anthropic, PBC | Proprietary / Commercial | HIGH |
| @openai/codex | OpenAI, Inc. | Proprietary / Commercial | HIGH |
| @google/gemini-cli | Google LLC | Proprietary / Commercial | HIGH |

All three tools are proprietary software distributed by their respective vendors
under terms that restrict redistribution and commercial use. Bundling them in a
Docker image and distributing that image to customers (or running them as a
multi-tenant SaaS) likely constitutes redistribution and/or embedding in a
commercial product. Each vendor's terms must be reviewed for:

- Whether bundling in a Docker image distributed to customers is permitted.
- Whether use in a multi-tenant SaaS (where one subscription enables AI calls on
  behalf of multiple end users) is permitted.
- Whether any per-seat or per-call licensing fees apply.

No NOTICE, license file, or vendor authorization letter for any of these tools
appears in the repository.

---

## Compliance Assessment

### What is Currently Compliant
- All Python open-source dependencies are permissively licensed and compatible with
  MIT distribution of the host project.
- All frontend CDN libraries are MIT or ISC licensed with no copyleft obligations.
- No GPL or AGPL dependencies are present that would require source disclosure of
  Bullpen itself.
- SRI hashes on CDN scripts reduce supply-chain risk and demonstrate good
  security practice.
- A `LICENSE.md` (MIT) is present in the repository root.

### What Requires Remediation

1. **No NOTICE / ATTRIBUTIONS file.** BSD-3-Clause (Flask) and MIT licenses
   require that copyright notices be retained in redistributed products. A `NOTICE`
   file must be generated and included in the Docker image and any other
   distribution artifact.

2. **websocket-client license election not documented.** The dual LGPL-2.1 /
   Apache-2.0 license should be explicitly resolved to Apache-2.0 in the project's
   NOTICE file to avoid LGPL obligations.

3. **Proprietary CLI redistribution not authorized.** The three AI CLI tools
   bundled in Docker have not been reviewed against their redistribution terms. This
   is the highest-risk item in the license audit.

4. **No Software Bill of Materials (SBOM).** The repository contains no SBOM
   (CycloneDX, SPDX) documenting the full dependency tree and their licenses. An
   acquirer should generate one prior to close.

5. **LICENSE.md lacks a named copyright holder.** As noted in the Brand & IP
   Audit, the MIT license text is incomplete. This is a gap in the license artifact
   itself.

---

## Findings

### HIGH — Proprietary AI CLIs Bundled in Docker Without Redistribution Authorization

`@anthropic-ai/claude-code`, `@openai/codex`, and `@google/gemini-cli` are all
proprietary commercial tools. The `Dockerfile` (or equivalent build scripts)
installs these tools via `npm` and bundles them into a Docker image. Distributing
a Docker image containing these tools to customers — or operating a multi-tenant
service where these tools execute on customers' behalf — may violate each vendor's
terms of service and/or require a commercial redistribution license.

**Risk**: Cease-and-desist, API/CLI access termination, or contractual liability.
This finding is compounded by the fact that the AI CLI tools are the core
functional components of the product, not peripheral utilities.

**Remediation**:
- Obtain written authorization (ToS review, partner agreement, or reseller
  agreement) from Anthropic, OpenAI, and Google before commercial launch.
- Consider an architecture where the CLI tools are installed by the end-user on
  their own infrastructure rather than bundled by the vendor — this shifts the
  redistribution liability to the customer.
- Alternatively, migrate to direct API integration (Anthropic API, OpenAI API,
  Google Generative AI API), which typically has clearer commercial terms for
  building products.

---

### MEDIUM — websocket-client LGPL-2.1 Path Not Explicitly Waived

`websocket-client` 1.9.0 is dual-licensed LGPL-2.1 OR Apache-2.0. Neither the
README nor any project file explicitly elects Apache-2.0. If LGPL-2.1 is the
operative license, the acquirer must ensure users can substitute the library — a
requirement that is satisfied by standard pip-based deployment but must be
documented. If the product is ever compiled into a binary or the library is
statically linked, LGPL-2.1 obligations become significantly more burdensome.

**Remediation**: Add an explicit Apache-2.0 election for `websocket-client` in the
project's NOTICE file. Example: "This product uses websocket-client, which is used
under the Apache License, Version 2.0."

---

### MEDIUM — No NOTICE File / Missing Attribution Artifacts

Flask (BSD-3-Clause) requires preservation of the copyright notice and disclaimer
in redistributed software. MIT licenses require preservation of copyright notices.
No `NOTICE`, `ATTRIBUTIONS`, or `THIRD_PARTY_LICENSES` file exists in the
repository or (presumably) the Docker image. This is a compliance gap for every
distributed artifact.

**Remediation**: Generate a NOTICE file using `pip-licenses --format=markdown` and
equivalent tooling for npm packages. Include this file in the Docker image and any
release artifact. Automate generation as part of the CI/CD pipeline.

---

### MEDIUM — No Software Bill of Materials (SBOM)

The repository has no SBOM in any standard format (SPDX, CycloneDX). Without an
SBOM, an acquirer cannot efficiently audit the full transitive dependency tree for
license compliance or vulnerability exposure. This is increasingly a regulatory
requirement in enterprise and government procurement.

**Remediation**: Generate an SBOM (e.g., using `syft` on the Docker image or
`pip-audit` + `cyclonedx-py` for Python). Commit the SBOM to the repository and
regenerate it on each release.

---

### LOW — LICENSE.md Missing Named Copyright Holder

The MIT license text in `LICENSE.md` does not name a copyright holder or year. A
valid MIT license requires both. This is primarily an IP ownership issue (covered
in the Brand & IP Audit) but also a license compliance issue: a downstream user
receiving the software cannot satisfy the MIT "retain copyright notice" obligation
if there is no copyright notice to retain.

**Remediation**: Amend `LICENSE.md` to read:
`Copyright (c) 2024-2026 [Seller Legal Name]. All rights reserved.`

---

### LOW — CDN Dependency Availability Risk (Not a License Issue, Noted for Completeness)

Frontend libraries are loaded from public CDNs. While SRI hashes protect against
content substitution, CDN unavailability would break the UI. This is an operational
risk, not a license risk, but is noted because a buyer conducting due diligence
often expects CDN dependencies to be vendored in a production product.

**Remediation**: Vendor frontend dependencies (copy into `static/vendor/`) or use
a reliable CDN with an SLA (e.g., a self-hosted copy behind the product's own CDN).
Update SRI hashes accordingly. This also eliminates any theoretical question about
whether CDN-loaded code constitutes "distribution" for license purposes.

---

### LOW — pytest Listed in requirements.txt Rather Than a Separate Dev Requirements File

`pytest` is a dev-only dependency. Including it in the primary `requirements.txt`
means it is installed in the production Docker image, increasing the attack surface
and image size. This is primarily a security/operational concern but could also
affect license artifact generation (dev tools are incorrectly surfaced as runtime
dependencies in SBOM output).

**Remediation**: Move `pytest` (and any other dev-only packages) to a separate
`requirements-dev.txt` and exclude it from the production Docker image build.

---

## Severity Summary Table

| Severity | Count |
|----------|-------|
| HIGH     | 1     |
| MEDIUM   | 3     |
| LOW      | 3     |

---

## Recommendations

1. **Resolve proprietary CLI redistribution before commercial launch** (HIGH). This
   is the most urgent item. Engage Anthropic, OpenAI, and Google legal/partnership
   teams. Consider an architecture shift to direct API integration or a
   "bring-your-own CLI" model where the tools are user-installed.

2. **Generate and commit a NOTICE file** covering all Python and npm dependencies.
   Use `pip-licenses` and `license-checker` to automate. Include the file in Docker
   images.

3. **Elect Apache-2.0 for websocket-client** explicitly in the NOTICE file.

4. **Generate an SBOM** (CycloneDX or SPDX format) from the Docker image and
   commit it to the repository. Automate regeneration in CI.

5. **Amend LICENSE.md** to name the copyright holder and year.

6. **Separate dev and production dependencies** — move `pytest` to
   `requirements-dev.txt`.

7. **Evaluate vendoring CDN dependencies** for production robustness (optional
   for license compliance, recommended for operational reliability).
