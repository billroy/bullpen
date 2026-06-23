# RFC: Bento Secure Carrier Format

Status: Draft

## 1. Abstract

Bento is a compressed, self-describing carrier format. A Bento file is a ZIP
archive with the filename extension `.bento` and a required `bento.json`
manifest at the archive root.

This document specifies the carrier rules: archive structure, path handling,
manifest envelope, labeled JSON attribute bundles, resource limits, verification
requirements, and security posture. It intentionally does not define exact
schemas for application objects carried inside the archive. Application-specific
meaning belongs to profiles layered on top of this carrier.

Bento is designed to let heterogeneous objects travel together safely. The
format provides a secure box and a manifest vocabulary for describing the box.
It does not make the contents safe to execute, import, render, or trust.

## 2. Terminology

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD",
"SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be
interpreted as described in RFC 2119.

**Bento file**: A ZIP archive conforming to this specification.

**Carrier**: The format defined by this document. The carrier is domain-neutral.

**Profile**: An application-specific interpretation of Bento contents. A profile
MAY define object conventions, import behavior, UI preview behavior, and
semantic validation.

**Manifest**: The required root JSON file `bento.json`.

**Item**: A manifest entry describing one payload member.

**Attribute bundle**: A labeled JSON bundle attached to the carrier, an item, or
a profile. Attribute bundles are metadata, not executable instructions.

**Payload member**: Any non-manifest file in the archive.

**Importer**: Software that reads a Bento file.

**Applier**: Software that applies Bento contents to an application workspace or
other stateful environment.

## 3. Design Goals

Bento SHALL provide:

- a neutral compressed carrier;
- a required manifest envelope;
- deterministic path and member handling;
- bounded resource consumption;
- a metadata mechanism for arbitrary labeled JSON bundles;
- profile discovery without profile lock-in;
- a security posture suitable for hostile input;
- room for future signing, scanning, and social distribution.

Bento SHALL NOT:

- require exact schemas for carried application objects;
- require any specific application domain, including Bullpen;
- confer trust on payload contents;
- execute or activate payload contents;
- require network access;
- require a scanner, signature, or registry in Stage 1.

## 4. File Identity

A Bento file:

- MUST be a ZIP archive.
- MUST contain `bento.json` at the archive root.
- SHOULD use the filename extension `.bento`.
- SHOULD use media type `application/vnd.bento+zip` when no vendor-specific media
  type is available.
- MAY use a vendor-specific media type such as
  `application/vnd.bullpen.bento+zip`.

Importers MUST NOT rely on filename extension alone. Importers MUST verify ZIP
structure and root `bento.json`.

## 5. Archive Structure

`bento.json` is REQUIRED. All other paths are OPTIONAL.

Recommended layout:

```text
bento.json
payload/
attributes/
assets/
metadata/
```

The carrier reserves these root names:

- `bento.json`
- `payload/`
- `attributes/`
- `assets/`
- `metadata/`

Profiles MAY define subdirectories under these roots. Profiles SHOULD NOT
require additional root directories unless necessary.

## 6. ZIP Member Requirements

Importers MUST enforce all of the following before applying any payload:

- Member names MUST be UTF-8 or ASCII-compatible names normalized by the ZIP
  reader into Unicode strings.
- Member names MUST use `/` as the path separator.
- Member names MUST NOT be empty.
- Member names MUST NOT begin with `/`.
- Member names MUST NOT contain `..` path segments.
- Member names MUST NOT contain Windows drive prefixes such as `C:`.
- Member names MUST NOT contain NUL bytes.
- Member names MUST NOT resolve outside the extraction root after filesystem
  normalization.
- Directory entries MAY be present.
- Symlinks, hard links, devices, FIFOs, sockets, and other special files MUST be
  rejected.
- Duplicate member names after normalization MUST be rejected.
- Encrypted ZIP entries MUST be rejected in Stage 1.
- Multi-disk ZIP archives MUST be rejected.
- Nested archives MUST be rejected by default.

Importers SHOULD validate without extracting when possible. If extraction is
needed, importers MUST extract only to a freshly-created temporary directory and
MUST validate paths before writing each file.

## 7. Resource Limits

Importers MUST enforce bounded resource consumption. The following Stage 1
limits are RECOMMENDED defaults:

| Limit | Default |
|-------|---------|
| Total ZIP entries | 256 |
| Total uncompressed bytes | 25 MiB |
| Single member uncompressed bytes | 5 MiB |
| Single JSON member bytes | 2 MiB |
| `bento.json` bytes | 512 KiB |
| Single attribute bundle bytes | 1 MiB |
| JSON nesting depth | 64 |
| ZIP compression ratio per member | 100:1 |
| Total ZIP compression ratio | 100:1 |
| Nested archive members | 0 |

Deployments MAY configure stricter or looser limits. Importers MUST fail closed
when limits are exceeded. Importers SHOULD report which limit failed.

## 8. Manifest Envelope

`bento.json` MUST be UTF-8 JSON. The root value MUST be an object.

The manifest MUST contain:

- `format`: string, MUST be `"bento"`.
- `version`: string, carrier version. This document defines `"1"`.
- `profiles`: array of profile descriptors. MAY be empty.
- `items`: array of item descriptors. MAY be empty.
- `attributes`: array of attribute bundle descriptors. MAY be empty.

The manifest MAY contain additional fields. Importers MUST preserve unknown
manifest fields when round-tripping unless producing a sanitized Bento.

Minimal manifest:

```json
{
  "format": "bento",
  "version": "1",
  "profiles": [],
  "items": [],
  "attributes": []
}
```

This specification deliberately does not constrain the manifest beyond the
envelope fields above. Profiles MAY define additional manifest fields. Generic
importers MUST treat profile-defined fields as data.

## 9. Profiles

Profiles declare semantic layers. A profile descriptor SHOULD contain:

- `id`: stable profile identifier.
- `version`: profile version.
- `label`: human-readable label.

Example:

```json
{
  "id": "org.bullpen.share",
  "version": "1",
  "label": "Bullpen Share"
}
```

Generic importers MUST NOT assume profile semantics. Profile-aware importers MAY
apply profile-specific validation and preview. If no supported profile is
present, an importer MAY preserve the Bento, inspect the manifest, or reject
application into local state.

Profiles MUST NOT weaken carrier-level validation requirements.

## 10. Items

An item descriptor describes a payload member or logical object. An item
descriptor MUST be a JSON object.

Item descriptors SHOULD contain:

- `id`: unique identifier within the Bento.
- `media_type`: media type or structured syntax hint.
- `path`: member path, if the item is file-backed.
- `label`: human-readable label.
- `attributes`: item-level attribute bundle descriptors.

Item descriptors MAY contain any additional fields. This carrier does not define
application object schemas. A Bento can carry JSON, text, binary assets, or any
other payload allowed by policy and resource limits.

If an item contains `path`, the path MUST refer to an existing non-directory
member and MUST pass all member validation rules. If an item contains a digest,
the importer MUST verify it before trusting the payload for preview or apply.

## 11. Attribute Bundles

Attribute bundles are arbitrary labeled JSON metadata. They MAY appear at the
manifest level, item level, or profile-defined locations.

An attribute bundle descriptor MUST be a JSON object and SHOULD contain:

- `label`: human-readable label.
- `namespace`: owner namespace, preferably reverse-DNS.
- `name`: stable bundle name within the namespace.
- `version`: bundle version.
- `data`: inline JSON value, OR
- `path`: path to a JSON member.

If both `data` and `path` are present, importers MUST prefer `data` and SHOULD
warn.

Attribute bundles MUST NOT be treated as executable instructions. Unknown
attribute bundles MUST be ignored for behavior and SHOULD be preserved for
round-trip export.

Attribute bundle paths MUST resolve to UTF-8 JSON members and MUST pass all
carrier validation. Importers MUST enforce attribute size and JSON depth limits.

## 12. Relationships

The carrier does not require a relationship model. Profiles MAY define one. A
generic convention is an attribute bundle with namespace `org.bento.relationships`
and a JSON array of relationship objects.

Relationships, when present, MUST be advisory. Importers MUST validate
relationships against actual payload contents before applying semantic effects.

## 13. Generic Processing Model

An importer MUST process a Bento in this order:

1. Verify ZIP structure.
2. Enumerate members.
3. Normalize and validate every member path.
4. Enforce resource limits.
5. Read and parse `bento.json`.
6. Validate manifest envelope fields.
7. Resolve and validate item paths.
8. Resolve and validate attribute bundle paths.
9. Verify declared digests, if present.
10. Build a preview model.
11. Request user or caller approval before applying effectful semantics.
12. Apply only through a profile-aware applier.

A generic importer MAY stop after step 10. A generic importer SHOULD NOT apply
payload contents to application state without a supported profile.

## 14. Security Posture

Bento files are untrusted input. This remains true when:

- the file extension is `.bento`;
- the file was produced by known software;
- the manifest looks well-formed;
- the file carries a future signature;
- a future scanner returns no findings.

Carrier security is about containment and safe inspection. It does not prove
semantic safety.

Importers MUST assume an attacker may craft Bento files to:

- exploit ZIP parser behavior;
- escape extraction directories;
- exhaust CPU, memory, file descriptors, or disk;
- smuggle executable content;
- confuse preview UI;
- hide dangerous semantics in unknown fields;
- create collisions in names, paths, IDs, or relationships;
- exploit downstream renderers;
- trick users into approving effectful imports.

Importers SHALL fail closed on malformed carrier structure, resource-limit
violations, invalid paths, duplicate normalized paths, unreadable manifest JSON,
and unsupported required profile behavior.

Importers MUST NOT execute scripts, commands, workers, hooks, or active content
while parsing, previewing, or importing the carrier.

Importers MUST NOT send Bento contents to a network service unless the caller or
user explicitly authorizes that transfer.

Importers SHOULD render preview text as untrusted text. If rich rendering is
provided, it MUST be sanitized or sandboxed according to the embedding
application's content-security model.

## 15. Manifest Flexibility and Security

A secure carrier can avoid imposing a strict domain manifest schema if it
separates carrier validation from profile semantics.

Carrier validation MUST be strict about:

- archive structure;
- path safety;
- resource limits;
- manifest parseability;
- required envelope fields;
- references from manifest to archive members.

Carrier validation SHOULD NOT require:

- exact item object schemas;
- fixed application object types;
- fixed relationship semantics;
- fixed attribute bundle schemas.

Profile validation handles semantic meaning. A profile-aware applier MUST inspect
payloads before applying them. Unknown fields are not inherently invalid, but
unknown fields that could cause effects MUST be treated as suspicious by the
profile-aware applier.

This division lets Bento be a secure generic carrier without becoming a rigid
application file format.

## 16. Preview and Apply

Importers SHOULD distinguish preview from apply.

Preview:

- MUST NOT mutate application state.
- MUST NOT execute payload contents.
- SHOULD summarize profiles, item counts, labels, media types, sizes, and
  declared capabilities when available.
- SHOULD expose conflicts and unsupported profile requirements.

Apply:

- MUST require a supported profile or explicit caller policy.
- MUST use an apply plan derived from preview.
- MUST require explicit approval for effectful semantics.
- MUST apply payloads in a dormant state unless a profile explicitly defines a
  safe alternative and the user approves it.

Effectful semantics include but are not limited to command execution, network
access, notifications, workflow dispatch, git mutation, filesystem writes outside
the target import area, opening URLs, and running automation.

## 17. Signing

Signing is not part of Stage 1.

Future signing support MUST address key material and trust. A signing design
would need:

- private-key generation or import;
- secure private-key storage outside Bento files;
- public-key discovery or distribution;
- trust-on-first-use, explicit allowlists, organization keys, or external
  identity binding;
- expiration and revocation;
- canonicalization of signed data;
- digest coverage for every signed member;
- a policy for unsigned or post-signature attribute bundles;
- UI language distinguishing provenance from safety.

A future signing design SHOULD sign a canonical statement containing the
manifest envelope and cryptographic digests of covered members. It SHOULD NOT
sign mutable ZIP metadata directly. Signatures SHOULD be stored under
`metadata/signatures/`.

A valid signature MUST NOT bypass carrier validation, profile validation,
preview, approval gates, or local policy. A signature says who signed a Bento; it
does not say the Bento is safe.

## 18. Scanner Integration

Scanner integration is not part of Stage 1.

Future scanner support MAY use local or remote providers. If remote scanning is
used, software MUST disclose that Bento contents may be transmitted to a third
party and MUST obtain user or caller authorization before transmission.

Scanner results SHOULD be represented as attribute bundles. Scanner results MUST
NOT weaken carrier validation. A scanner pass MUST NOT imply that payloads are
safe to execute.

Deferred scanner questions include:

- provider selection;
- local versus remote scanning;
- sanitized output versus findings only;
- finding severity thresholds;
- object lockout;
- remediation and rescan;
- audit trails.

## 19. Stage 1 Compliance

A Stage 1 compliant Bento importer MUST:

- recognize Bento by ZIP structure plus root `bento.json`;
- enforce member path rules;
- enforce resource limits;
- parse the manifest envelope;
- validate item and attribute paths;
- preserve unknown manifest fields and attribute bundles when round-tripping;
- produce a safe preview model;
- refuse application without a supported profile or explicit caller policy;
- require approval for effectful apply operations;
- reject malformed or unsafe carriers before apply.

Stage 1 compliant producers MUST:

- write valid ZIP archives;
- write root `bento.json`;
- use `format: "bento"` and `version: "1"`;
- use safe relative member paths;
- avoid duplicate normalized paths;
- avoid unnecessary active content;
- avoid embedding secrets or host-specific runtime state unless the producer
  clearly marks the Bento as diagnostic and the user chooses that export mode.

## 20. Profile: Bullpen Share (Informative)

Bullpen MAY define an application profile such as:

```json
{
  "id": "org.bullpen.share",
  "version": "1",
  "label": "Bullpen Share"
}
```

That profile can define how Bullpen workers, tickets, worksheets, values, and
project templates are previewed and applied. Those rules are not carrier rules.

Bullpen profile import SHOULD:

- import objects dormant;
- strip runtime state by default;
- preserve placement when no conflicts exist;
- ask on placement conflicts;
- import tickets into human-controlled columns;
- disable or lock command-capable objects until approved;
- never enqueue or run imported objects during import.

## 21. Open Issues

- Bullpen profile policy: command-capable imports disabled or enabled-but-locked.
- Bullpen profile policy: default ticket destination.
- Bullpen profile policy: minimum producer/version metadata for compatibility
  warnings.
