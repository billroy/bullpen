# App Authenticity Runtime

## Status

Draft specification, June 2026.

This document describes a proposed architecture for local desktop applications
that ship embedded services, helper binaries, sandbox images, runtimes, local
servers, model assets, or other executable components. The goal is to replace
the current "YOLO shell command" and "trust this DMG" installation culture with
a local runtime model that makes installed assets, running components, drift,
repair, and uninstall visible and verifiable.

The working name in this document is **App Authenticity Runtime**. The name is
less important than the shape: provenance plus lifecycle plus asset custody.

## Problem

Modern desktop applications are increasingly small local distributed systems.
A single visible app may include:

- a native UI process
- local HTTP servers
- background workers
- helper binaries
- sandbox or container runtimes
- embedded databases
- file watchers
- browser previews
- update helpers
- model weights
- language runtimes
- agent subprocesses
- local sockets and ports

Today these pieces are usually deployed through fragile and opaque mechanisms:

- one-line shell installers
- DMGs and PKGs with hidden postinstall behavior
- app bundles with undocumented helpers
- user launch agents
- ad hoc sidecars
- container stacks
- invisible caches and state directories
- bespoke update checkers

These systems answer "how do I put bytes on disk?" but not:

- What exactly was installed?
- Who built each artifact?
- Which artifacts are immutable and which are mutable?
- Which services are allowed to run?
- Why is a service running now?
- What files, ports, devices, secrets, and network paths can it touch?
- Is the installed state still valid?
- Has anything drifted or been corrupted?
- Can corrupted assets be repaired?
- Can every component be stopped?
- Can the whole app be removed without residue?

The result is random local state: support-hostile, user-hostile, and difficult
to inspect. The runtime proposed here treats local app deployment as an
auditable custody problem.

## Non-Goals

This is not a universal package manager.

This is not a replacement for every platform-specific primitive. macOS may use
app bundles, code signing, Keychain, XPC, or process groups underneath. Linux
may use cgroups, namespaces, portals, DBus, systemd user units, or process
groups underneath. Those are backend details, not the user-facing truth.

This is not a claim that every component can be perfectly sandboxed on every
platform. The runtime must distinguish enforced policy from advisory policy.

This is not a hidden process supervisor. Hidden OS machinery may implement
lifecycle, but it must not be where app truth lives.

This is not an agent control surface. It must not infer task meaning, inspect
application semantics, or become a second orchestrator around a domain-specific
app. It supervises components and assets, not work.

## Design Principles

### Normal artifacts remain normal

An app remains an app. A local server remains a process. A database remains a
database. A log remains a log. The authenticity layer is metadata and custody
around those things, not a proprietary replacement for them.

This mirrors the Writing Witness principle:

```text
The file on disk is the document.
The provenance record is synchronized metadata.
```

The runtime equivalent is:

```text
The app/service is the thing being run.
The manifest/hash graph is its provenance and custody record.
```

### The manifest is the contract

Every component, asset, capability, lifecycle rule, health check, repair rule,
and uninstall rule is declared in a signed manifest.

The manifest is the user-facing and support-facing truth. Platform primitives
may implement it, but they do not define it.

### Immutable assets are content-addressed

Binaries, runtimes, sandbox images, static web assets, templates, verifier
assets, and other immutable artifacts are addressed by hard hashes.

The runtime can verify them, detect drift, repair them from a local content
store, or fetch known-good replacements from a trusted update source.

### Mutable state is structured and recoverable

Mutable state is not treated as corrupt merely because it changed. It has its
own integrity model: database checks, schema validation, snapshots, journals,
append-only records, retention policy, and repair behavior.

### Lifecycle is visible

The user and support should be able to answer:

```text
What is running?
Why is it running?
What started it?
What can it touch?
How do I stop it?
Where are its logs?
What happens if I uninstall?
```

### Claims are calibrated

The runtime must report what it can actually prove:

- verified installed assets
- detected drift
- repaired corrupted immutable assets
- mutable state passed integrity checks
- declared lifecycle matched observed lifecycle
- capability policy enforced
- capability policy advisory
- capability policy unavailable

It must not overclaim "safe", "secure", or "uncompromised" merely because
hashes match.

### Content is externally scanned

Every content item admitted into the runtime's custody graph must be scanned by
one or more external scanning services before it is trusted, launched, served,
or made available to a managed component.

In this document, **external** means independent from the app component,
publisher binary, or helper process that wants to use the content. A scanner may
be a local service, a remote service, an enterprise service, or an OS-provided
service, but its result is a separate attestation over the content hash.

Scanning is not a substitute for hashing, signing, sandboxing, or capability
policy. It is an additional custody requirement:

```text
content hash
+ publisher signature
+ scanner attestations
+ lifecycle/capability policy
```

The runtime must distinguish scanning immutable install artifacts from scanning
private mutable user content. Private content must not be sent to remote
scanners without explicit policy and user consent. Local external scanners are
preferred for privacy-sensitive content.

## System Overview

The proposed system has six major layers:

```text
1. Signed app manifest
2. Content-addressed immutable asset store
3. Mutable state registry
4. Component lifecycle supervisor
5. External scanner integration and scan attestations
6. Verifier, repair, and garbage-collection engine
```

The user-visible surface presents the app as a component graph:

```text
Bullpen
  UI app             running
  ticket server      running   127.0.0.1:5050
  sandbox runtime    stopped
  worker manager     running

Assets
  app binary         verified
  server binary      verified
  web assets         verified
  sandbox image      verified
  ticket database    healthy
  cache              disposable

Actions
  stop all
  restart component
  view logs
  verify assets
  repair
  uninstall completely
```

## Manifest Model

The manifest declares identity, artifacts, components, capabilities,
lifecycle, health, logs, repair, scanning, updates, and uninstall behavior.

Example sketch:

```yaml
schema_version: 1
app:
  id: com.example.bullpen
  name: Bullpen
  version: 1.4.2
  publisher: Example Software

artifacts:
  ui-binary:
    type: executable
    mutability: immutable
    hash: blake3:...
    signature: ...
    scanning:
      required_profiles:
        - malware
        - vulnerability
        - sbom
      fail_closed: true
    repair: replace-from-store-or-update

  server-binary:
    type: executable
    mutability: immutable
    hash: blake3:...
    signature: ...
    scanning:
      required_profiles:
        - malware
        - vulnerability
        - sbom
        - secrets
      fail_closed: true
    repair: replace-from-store-or-update

  web-assets:
    type: directory-tree
    mutability: immutable
    merkle_root: blake3:...
    scanning:
      required_profiles:
        - malware
        - active-content
        - secrets
      fail_closed: true
    repair: replace-corrupt-tree-members

  ticket-db:
    type: sqlite
    mutability: mutable
    path: state/tickets.db
    integrity:
      check: sqlite-integrity-check
      snapshots: true
      journal_replay: true
    scanning:
      required_profiles:
        - schema-policy
      remote_allowed: false
    repair: replay-journal-or-restore-snapshot

  service-logs:
    type: logs
    mutability: append-only
    retention: 14d
    repair: truncate-corrupt-tail

components:
  ui:
    kind: app
    artifact: ui-binary
    lifetime: user-launched

  ticket-server:
    kind: service
    artifact: server-binary
    command:
      - bullpen-server
      - --port
      - "5050"
    lifetime: while-app-open
    health:
      http: http://127.0.0.1:5050/healthz
      interval: 10s
    network:
      listen:
        - 127.0.0.1:5050
      egress: loopback-only
    filesystem:
      - path: workspace
        access: rw
    logs:
      stdout: service-logs
      stderr: service-logs
    restart:
      policy: manual

updates:
  channel: stable
  metadata: tuf
  transparency_log: optional

scanners:
  malware-primary:
    service: com.example.scanners.malware
    profiles:
      - malware
    mode: local-or-remote
    required: true

  vulnerability-primary:
    service: com.example.scanners.vulnerability
    profiles:
      - vulnerability
      - sbom
    mode: remote
    required: true

  privacy-local:
    service: com.example.scanners.privacy-local
    profiles:
      - secrets
      - active-content
      - schema-policy
    mode: local
    required: true

uninstall:
  remove:
    - immutable-assets
    - cache
    - logs-after-confirmation
  preserve:
    - user-documents
  ask:
    - mutable-state
```

## Asset Classes

### Immutable assets

Immutable assets are expected to match their manifest identity exactly.

Examples:

- app binaries
- helper binaries
- language runtimes
- static web assets
- sandbox base images
- model weights
- verifier tools
- templates

Verification:

- path exists
- content hash matches
- code signature or artifact signature matches
- artifact belongs to expected publisher/update channel
- executable permissions match policy

Repair:

- replace from local content-addressed store
- fetch from trusted update source
- verify hash and signature before activation
- restart affected components when required

### Mutable state

Mutable state is allowed to change but must be declared.

Examples:

- SQLite databases
- app preferences
- workspace state
- user-managed config
- append-only logs
- generated indexes

Verification:

- schema validation
- database-native integrity checks
- checksum verification where available
- snapshot lineage checks
- journal consistency checks

Repair:

- journal replay
- restore last-known-good snapshot
- migrate forward
- preserve broken copy for support
- declare unrecoverable state when repair cannot be proven

### Ephemeral assets

Ephemeral assets are expected to appear and disappear.

Examples:

- sockets
- PID files
- temporary directories
- locks
- short-lived cache files

Verification:

- ownership
- location
- stale detection

Repair:

- delete stale entries
- recreate as needed

### Secret references

Secrets should be tracked as references, not ordinary hashable files.

Examples:

- Keychain items
- Secret Service entries
- local tokens
- signing keys

Verification:

- reference exists
- access control matches expected component
- key identity matches expected public key or key ID
- secret is not exported in manifests or logs

Repair:

- re-provision
- rotate
- ask user

## Hashing and Signing

Hard hashes are appropriate for immutable assets.

Recommended technologies:

- BLAKE3 for fast local verification
- SHA-256 or SHA-512 where ecosystem compatibility requires it
- Merkle trees for large directory trees, model files, and sandbox images
- platform code signing for OS identity
- artifact signatures for cross-platform identity
- TUF-style metadata for update safety
- transparency logs or Sigstore-style attestations where appropriate

Large assets should be chunk-addressed when repair would otherwise require a
full redownload:

```text
model.bin
  root hash
  chunk size
  chunk hashes
  corrupted chunk 1842
  fetch chunk 1842
  verify chunk
  verify root
```

Canonical manifest signing must be deterministic. The canonicalization rules
must be part of the spec, and independent verifier fixtures must exist.

## External Scanning and Attestation

All content in the custody graph must have scan coverage appropriate to its
asset class before it can be trusted by the runtime.

### Scan scope

The runtime scans:

- immutable install artifacts
- update payloads
- helper binaries
- scripts
- templates
- static web assets
- model files
- sandbox images
- generated executable content
- mutable databases and config according to declared policy
- user-provided content when a managed component will execute, serve, index, or
  transform it

The runtime does not treat "already signed by the publisher" as sufficient.
Publisher identity answers who supplied the content. Scanning answers whether
independent services found known-risk properties in that exact content.

### Privacy boundary

Content scanning must be hash-bound and policy-bound.

Remote scanning of private user content is disabled by default. If a component
requires remote scanning of private content, the manifest must say so, the UI
must expose it, and the user must approve it.

Local external scanners may inspect private content without network
transmission. They still count as external if they are independent scanner
services with signed scan results, not inline app code marking its own content
as clean.

The runtime should support three privacy modes:

```text
hash-only remote lookup
local content scan
remote content scan with explicit approval
```

Hash-only remote lookup is useful for known malware and reputation databases,
but it is not sufficient for novel content. The scan result must report whether
the scanner inspected content bytes or only checked the hash.

### Scan profiles

Common scan profiles:

- malware
- vulnerability
- SBOM generation
- license policy
- secret detection
- active-content detection
- script policy
- model safety metadata
- archive traversal/path safety
- schema/config policy
- native code signature validation
- dependency reputation

Profiles are composable. A binary artifact may require malware, vulnerability,
SBOM, and signature validation. A web asset tree may require malware,
active-content, and secret scanning. A mutable SQLite database may require
schema-policy and database-integrity profiles.

### Scan request interface

Scanner services receive a scan request keyed to content identity.

Example request:

```json
{
  "schema_version": 1,
  "request_id": "scanreq_01J...",
  "runtime_id": "app-auth-runtime",
  "app_id": "com.example.bullpen",
  "artifact_id": "server-binary",
  "content": {
    "type": "file",
    "hash_algorithm": "blake3",
    "hash": "b3...",
    "size_bytes": 18432012,
    "media_type": "application/x-mach-binary",
    "path_hint": "Components/server/bin/bullpen-server"
  },
  "profiles": [
    "malware",
    "vulnerability",
    "sbom",
    "secrets"
  ],
  "privacy": {
    "mode": "local-content-scan",
    "remote_content_allowed": false,
    "hash_lookup_allowed": true
  },
  "policy": {
    "fail_closed": true,
    "max_age_seconds": 604800
  },
  "nonce": "base64..."
}
```

For directory trees and large artifacts, the request may reference a Merkle
root and chunk table rather than a single file hash.

### Scan result interface

A scanner returns a signed scan attestation over the request, content identity,
profiles, verdicts, and scanner identity.

Example result:

```json
{
  "schema_version": 1,
  "request_id": "scanreq_01J...",
  "scanner": {
    "id": "com.example.scanners.malware",
    "name": "Example Malware Scanner",
    "version": "4.8.1",
    "signature_key_id": "key_2026_05"
  },
  "content": {
    "hash_algorithm": "blake3",
    "hash": "b3...",
    "size_bytes": 18432012
  },
  "scan": {
    "started_at": "2026-06-02T18:00:00Z",
    "completed_at": "2026-06-02T18:00:03Z",
    "mode": "local-content-scan",
    "profiles": {
      "malware": {
        "verdict": "pass",
        "engine_version": "2026.06.02",
        "definitions_version": "2026.06.02.3"
      },
      "vulnerability": {
        "verdict": "warn",
        "findings": [
          {
            "id": "CVE-...",
            "severity": "medium",
            "component": "libexample",
            "policy_action": "warn"
          }
        ]
      },
      "sbom": {
        "verdict": "pass",
        "sbom_hash": "sha256:..."
      },
      "secrets": {
        "verdict": "pass"
      }
    },
    "overall_verdict": "warn"
  },
  "signature": {
    "algorithm": "ecdsa-p256-sha256",
    "canonicalization": "app-auth-json-v1",
    "value": "base64..."
  }
}
```

Verdicts:

```text
pass
warn
fail
unverified
unsupported
expired
```

The runtime evaluates scanner results against manifest policy. A warning may be
acceptable for one profile and blocking for another. Missing, expired, unsigned,
or hash-mismatched scan results are not valid.

### Scan attestation storage

Scan results are stored as first-class custody records:

```text
manifests/
scan-attestations/
  <content-hash>/
    <scanner-id>-<profile>-<timestamp>.json
```

Each attestation binds to:

- content hash or Merkle root
- artifact ID
- app ID
- scanner identity
- scanner version
- scan profile
- scan mode
- scan time
- policy result

When content changes, previous scan attestations no longer apply. When scanner
definitions age out, the runtime may mark the content as needing rescan.

### Scanner discovery

Scanner services are discovered through a registry:

```json
{
  "schema_version": 1,
  "scanner_id": "com.example.scanners.malware",
  "display_name": "Example Malware Scanner",
  "service_endpoint": "unix:///.../scanner.sock",
  "remote_endpoint": "https://scanner.example.com/v1/scan",
  "profiles": ["malware", "archive-traversal"],
  "modes": ["hash-lookup", "local-content-scan", "remote-content-scan"],
  "public_keys": [
    {
      "key_id": "key_2026_05",
      "algorithm": "ecdsa-p256-sha256",
      "public_key_spki": "base64..."
    }
  ],
  "privacy": {
    "retains_content": false,
    "retains_hashes": true,
    "remote_content_default": false
  }
}
```

The scanner registry can be OS-provided, enterprise-provided, or
runtime-managed. The runtime must show which scanner services are trusted and
why.

### Required scanner service types

The runtime should define service descriptions for at least these scanner
classes:

**Malware scanner**

Detects known malware, suspicious binaries, archive bombs, traversal payloads,
and known hostile scripts. Supports hash lookup and content scanning.

**Vulnerability and dependency scanner**

Builds or consumes an SBOM and checks known vulnerable dependencies, runtime
libraries, embedded packages, and native libraries. Must report the data source
and database freshness.

**SBOM generator**

Produces a Software Bill of Materials for immutable artifacts and dependency
trees. The SBOM hash becomes part of the scan attestation.

**License scanner**

Reports dependency and embedded asset licenses against policy. This is not a
security scanner, but it is part of install provenance.

**Secret scanner**

Detects accidentally embedded keys, tokens, credentials, private URLs, and
other secrets in install artifacts, scripts, configs, web assets, and generated
content.

**Active-content scanner**

Detects scripts, remote resource references, HTML injection risks, executable
markup, macros, browser-triggered network loads, and other active content in
assets that might be displayed or served.

**Config/schema policy scanner**

Validates mutable config and database state against declared schemas and
policy. It reports malformed state, unexpected keys, unsafe paths, undeclared
ports, and policy drift.

**Model asset scanner**

Inspects model files and related metadata for declared provenance, expected
format, hash identity, license, size, quantization/type, and known-risk metadata.
It does not claim to prove model behavior safe.

### Enforcement points

The runtime must enforce scan policy at these points:

- install
- update
- repair
- first launch
- component start
- content import into managed custody
- before a managed component executes, serves, or indexes user-provided content
- before opening active content in an embedded browser or preview

Enforcement can be fail-closed or fail-open with warning, as declared by
manifest policy. Executable immutable artifacts should default to fail-closed.

### User-visible scan state

The UI must show:

- scan profiles required
- scanner services used
- last scan time
- whether bytes or only hashes were scanned
- whether content was sent remotely
- scan verdicts
- expired scans
- missing scans
- failed scans
- warnings and policy decisions

For private content, the UI must make remote scanning explicit.

## Runtime Verification

At rest, the runtime verifies assets and state:

- immutable asset hashes
- scan attestation validity
- signatures
- manifest validity
- mutable state integrity
- orphaned assets
- undeclared files in managed stores

At runtime, it verifies observed process state:

- process executable hash matches declared component
- command line matches manifest
- process group matches runtime ownership
- working directory matches policy
- exposed ports match declared ports
- health checks pass or fail
- restart count is recorded
- environment variables match declared grants where practical
- logs are routed to declared sinks

The runtime should report drift explicitly:

```text
server binary: hash mismatch
ticket server: running undeclared executable
port 5051: exposed by unknown component
ticket-db: integrity check failed
cache: stale, rebuilt
```

## Repair

Repair is per asset class and per component.

Repair must be a first-class action, not a support ritual.

Example repair decisions:

```text
Immutable binary corrupt:
  stop affected component
  replace from verified CAS
  verify hash/signature
  restart only if lifecycle policy permits

Sandbox image corrupt:
  stop sandbox component
  repair corrupt chunks or redownload image
  preserve writable overlay only if overlay integrity passes
  otherwise offer snapshot restore or reset

SQLite database corrupt:
  stop affected components
  run database-native integrity check
  replay journal
  restore last-known-good snapshot if needed
  preserve corrupt copy for support

Cache corrupt:
  delete and regenerate

Config invalid:
  validate schema
  restore last-known-good
  preserve invalid file for inspection
```

Repair actions should produce signed or hash-chained local events so the
runtime can answer how the current state came to be.

## Lifecycle

Components declare a lifetime:

- user-launched
- while-app-open
- while-workspace-open
- on-demand
- at-login
- persistent
- manual-only

The default for local app services should be narrow:

```text
while-app-open
while-workspace-open
manual-only
```

Persistent components require explicit user approval and visible status.

Lifecycle operations:

- start
- stop
- restart
- stop all
- suspend
- resume
- tail logs
- verify component
- repair component

The runtime should supervise process groups rather than individual PIDs when
possible, so child processes do not escape component ownership.

## Capability Model

Capabilities are declared per component, not only per app.

Capability domains:

- filesystem
- network listen
- network egress
- local ports
- secrets
- devices
- GPU/accelerators
- browser/open-url authority
- notifications
- IPC/socket access
- environment variables

Each declared capability should report enforcement status:

```text
enforced
advisory
unavailable
unknown
```

This is essential for cross-platform honesty. Linux may enforce a policy via
namespaces, cgroups, seccomp, and portals. macOS may enforce some policies via
app sandboxing, XPC boundaries, Keychain ACLs, and TCC, while other policies
remain advisory for direct child processes.

The runtime must not imply that advisory policy is sandbox enforcement.

## User Interface Requirements

The UI must be boring and explicit.

Required views:

- installed apps
- component graph
- current runtime state
- asset verification state
- mutable state health
- logs
- ports
- permissions/capabilities
- repair actions
- uninstall/garbage collection

The UI should let a user or support person answer:

```text
What is this app running?
Why is it running?
What version is each component?
Which assets are verified?
Which state is mutable?
Which local ports are open?
What can each component access?
What failed?
What was repaired?
What can be removed?
```

The UI must not hide truth in platform-specific magic folders. If a backend
uses launchd, systemd user units, XPC, DBus, or process groups, that may be
shown as implementation detail, but the runtime manifest and registry remain
the primary truth.

## macOS Backend Shape

macOS wants an app-bundle-first model:

```text
Bullpen.app/
  Contents/
    MacOS/
    Resources/
      app-authenticity.manifest.json
    Components/
      ticket-server/
      verifier/
      sandbox-helper/
```

Managed state:

```text
~/Library/Application Support/Bullpen/
  manifests/
  store/
  state/
  logs/
  cache/
```

Recommended backend choices:

- app bundle for primary app identity
- code signing and notarization for platform identity
- signed manifest for component identity
- Keychain for secrets and signing keys
- direct child processes/process groups for workspace-scoped services
- XPC services for strongly separated helpers
- SMAppService only for explicit login/persistent helpers
- launchd only as buried backend, never as user-facing truth

macOS strengths:

- strong app identity
- mature signing/notarization
- natural app bundle ownership
- Keychain
- XPC for helper separation

macOS weaknesses:

- hidden lifecycle state is common
- launch agents are user-hostile as a visible control regime
- component-level capability enforcement is uneven
- observability is flat and scattered
- uninstall discipline is weak

The runtime should compensate by making component state visible and by keeping
supportable truth in the manifest/registry.

## Linux Backend Shape

Linux wants a bundle/container/portal/process-control model.

Possible physical packaging forms:

- Flatpak-style sandboxed app
- AppImage-style self-contained bundle
- OCI/Nix-style content-addressed closure
- distro package that installs a signed runtime manifest

Managed state:

```text
~/.local/share/<app-id>/
  manifests/
  store/
  state/
  logs/
  cache/

~/.config/<app-id>/
  user-config
```

Recommended backend choices:

- content-addressed immutable store
- user-scoped supervisor
- process groups
- cgroups for accounting and limits
- namespaces/seccomp/bubblewrap for sandboxing
- portals for user-mediated capabilities
- Secret Service/libsecret for secrets
- DBus where useful
- systemd user units only as an optional backend, never as the truth

Linux strengths:

- strong isolation primitives
- cgroups for resource accounting
- namespaces and seccomp
- Flatpak/portal precedent
- content-addressed ecosystems already exist

Linux weaknesses:

- packaging fragmentation
- inconsistent desktop integration
- inconsistent provenance story across channels
- too many backend options
- user-facing polish is weak

The runtime should compensate by offering one manifest and custody model with
multiple native backend implementations.

## Relationship To Writing Witness

Writing Witness is a sibling project focused on provenance and attestability
for personal written assets. Its core architecture maps directly:

```text
Writing Witness:
  file on disk
  CRDT/Merkle edit history
  signed batches
  timestamp anchoring
  independent verifier

App Authenticity Runtime:
  app/service graph on disk and in process
  manifest/Merkle asset history
  signed lifecycle and repair events
  optional timestamp anchoring
  independent verifier
```

Writing Witness asks:

```text
How did this text come to be?
```

This runtime asks:

```text
How did this local app system come to be, and is it still the system that was
installed?
```

The projects can share:

- canonical JSON rules
- signed record formats
- verifier patterns
- timestamp anchoring strategy
- local-first privacy discipline
- calibrated claims language
- sealing-completeness analysis
- test fixtures for independent verification

The difference is that Writing Witness can make stronger claims about document
mutation because it owns the editor pipeline. The runtime cannot always own
every OS primitive, so it must be especially explicit about what is enforced,
what is observed, and what is merely declared.

## Threat Model

The runtime is useful against:

- accidental corruption
- incomplete installs
- stale or orphaned assets
- helper binary drift
- update mistakes
- support ambiguity
- unauthorized local modification of immutable assets
- undeclared running components
- port surprises
- residue after uninstall
- mutable state corruption with recoverable snapshots

The runtime is not sufficient by itself against:

- a fully compromised OS account
- malicious signed publisher updates
- kernel compromise
- all forms of secret exfiltration
- all forms of runtime process injection
- platform primitives that cannot enforce declared policy

The runtime should still make compromise more visible by detecting drift from
declared assets and lifecycle.

## Verification Artifacts

The runtime should support independent verification through exportable
artifacts:

- manifest
- installed asset hashes
- scan attestations
- component inventory
- lifecycle event log
- repair event log
- mutable state integrity summaries
- public signing keys or certificate chain
- update metadata
- verifier version

Exports should be readable as JSON and optionally as a self-contained HTML
viewer, following the Writing Witness pattern.

## Events

Lifecycle and custody events should be recorded locally:

- install
- verify
- start
- stop
- crash
- restart
- repair
- update
- rollback
- mutable state snapshot
- mutable state restore
- capability grant
- capability revocation
- uninstall
- garbage collection

Events should be hash-chained or batch-signed when they carry evidentiary
weight. The system should identify which events are sealed and which are only
local logs.

## Updates

Updates are part of the custody model.

An update changes the manifest and one or more assets. It should be:

- authenticated
- atomic
- rollback-capable
- scoped by component
- recorded as an event
- followed by verification

The runtime should retain enough prior state to answer:

```text
What changed?
Which component changed?
Who signed the change?
Which assets were removed?
Which assets were added?
Can I roll back?
```

## Uninstall and Garbage Collection

Uninstall is a declared operation, not "drag app to trash and hope".

The runtime knows every owned asset and can classify it:

- immutable app asset: remove
- cache: remove
- logs: remove or ask
- mutable user state: ask
- user documents: preserve
- secrets: revoke or ask
- persistent services: stop and unregister
- sockets and temporary files: remove
- orphaned assets: remove when unreferenced

The uninstall report should say what was removed, what was preserved, and what
could not be removed.

## Minimal Viable Scope

A practical first version should not try to become a universal secure
deployment platform.

Minimum useful scope:

- manifest schema
- immutable asset hashing
- external scan request/result schema
- scan attestation storage
- required scan policy for immutable executable assets
- local asset registry
- component start/stop/restart
- process group ownership
- log capture
- health checks
- port inventory
- mutable state declarations
- basic SQLite/config integrity checks
- repair for immutable assets and disposable cache
- uninstall inventory
- macOS and Linux backend prototypes
- independent verifier for manifest/assets
- independent verifier for scan attestation signatures and hash binding

Explicitly defer:

- universal sandbox enforcement
- enterprise policy
- cloud control plane
- all-platform package management
- complex dependency solving
- remote attestation
- marketplace distribution
- universal remote scanning of private user content

## Technical Risk

Low to medium risk:

- content-addressed asset storage
- hard hash verification
- manifest signing
- repair from known-good assets
- log capture
- health checks
- uninstall inventory
- independent verifier tooling
- scanner request/result protocols
- scan attestation verification

Medium risk:

- cross-platform lifecycle abstraction
- process group ownership and cleanup
- clean UI for component state
- mutable state repair without data loss
- update and rollback ergonomics
- scanner freshness, false positives, and policy tuning

High risk:

- capability enforcement across macOS and Linux
- preserving an honest distinction between enforced and advisory policy
- avoiding a leaky abstraction over platform service managers
- adoption by app developers
- privacy-preserving scanning of user content
- dependency on external scanner availability and trust roots

Very high risk:

- becoming a general-purpose app deployment substrate
- replacing existing packaging ecosystems
- broad security claims
- enterprise-grade policy and audit

The recommended path is to build custody plus lifecycle first, prove it with
one concrete app, and only then expand.

## Bullpen Relevance

Bullpen is exactly the kind of app that exposes this need. It has local app
state, long-running services, sandboxed components, local ports, logs, and
support-sensitive lifecycle concerns.

Bullpen should own Bullpen semantics: tickets, agents, browser clients,
Socket.IO events, workspace state, and task orchestration.

An App Authenticity Runtime should own only the outer mechanical layer:

- start this service
- stop this service
- capture logs
- verify this asset
- repair this corrupted binary
- report this port
- uninstall this owned state

It must not become a second Bullpen manager. It is a fuse box, not a foreman.

## North Star

The user should be able to ask any local app:

```text
What are you?
Where did your pieces come from?
What are you running?
Why are you running it?
What can it touch?
Are your assets still valid?
What changed?
Can you repair yourself?
Can I stop you?
Can I remove you completely?
```

The app should be able to answer without folklore, hidden plists, support
scripts, or archaeology.
