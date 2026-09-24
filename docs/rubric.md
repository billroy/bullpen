# Work Product Handoff Rubric

Bullpen tickets should carry file-based work product information between workflow steps using a small, human-readable Markdown convention. The convention describes what a step produced, not how another step should consume it.

## Core convention

Use a `## Work Products` section containing workspace-relative Markdown links and plain-language descriptions:

```markdown
## Work Products

### Newsletter Writer

- [Morning newsletter](reports/morning-newsletter.html) — HTML newsletter covering completed work for August 26.
- [Plain-text edition](reports/morning-newsletter.txt) — Text equivalent of the newsletter.
```

Each entry communicates:

- A human name for the product.
- A weak reference to an ordinary workspace file.
- A factual description of what the file contains or represents.

The entry must not direct a later step to email, publish, deploy, approve, or otherwise act on the product.

## Separation of responsibilities

- **Producer:** records the files it made, what they are, and useful relationships to earlier products.
- **Consumer:** decides which available product it can use according to its own configuration or instructions.
- **Workflow:** controls routing, ordering, queues, activation, and success or failure behavior.

Product information must not encode workflow control. An originating worker need not know whether its HTML will later be reviewed, scanned, emailed, published to a site, converted to PDF, archived, or used by a human.

## Accumulation through a workflow

Each step appends its own subsection and products. A long-running ticket can therefore accumulate a readable record:

```markdown
## Work Products

### Newsletter Writer

- [Newsletter draft](reports/newsletter-draft.html) — Initial HTML newsletter.

### Copy Editor

- [Edited newsletter](reports/newsletter-edited.html) — Copy-edited version of the newsletter draft.
- [Editorial notes](reports/editorial-notes.md) — Changes and unresolved editorial questions.

The edited newsletter was derived from the
[newsletter draft](reports/newsletter-draft.html).

### Safety Review

- [Safety review](reports/safety-review.md) — Review of the edited newsletter; no blocking findings.
- [Reviewed newsletter](reports/newsletter-reviewed.html) — Newsletter incorporating the required disclosure correction.
```

Relationships such as “derived from,” “reviews,” “contains,” and “supersedes” should be expressed with ordinary prose and links. They are useful shared vocabulary, not reserved fields or a formal schema.

## Why Markdown

The same representation is intelligible at several levels:

- A simple program can find file links.
- A deterministic worker can filter candidates by path, extension, or inspected media type.
- An agent can interpret descriptions, provenance, and relationships.
- A human can inspect, edit, and use the record directly.

There should be no hidden JSON manifest or more-authoritative parallel representation. Bullpen may provide a convenience action for appending entries, but humans and agents must be able to produce the same effective record by editing the ticket Markdown.

## Authoring rules

- Use workspace-relative links.
- Use noun phrases for product names, not commands.
- Describe what a file contains or represents, not what the next worker should do.
- Finish writing a file before adding its product link.
- Prefer new paths for derived versions instead of silently overwriting earlier products.
- Append new step subsections rather than rewriting another step's account.
- State replacement or lineage in prose when it matters.
- Keep progress narration and non-file commentary outside `## Work Products`.
- Treat missing or unsafe links as broken ticket information rather than guessing.

## Consumer behavior

Selection policy belongs to the consuming worker. For example, an email notification worker may be configured to select an externally suitable HTML newsletter, while a safety worker may select the most recent newsletter candidate and produce a review report.

If no suitable product exists, the consumer should fail clearly. If several products satisfy its policy and it cannot distinguish them, it should report ambiguity rather than relying on an accidental list order.

When resolving a link, Bullpen should ensure that it remains inside the workspace, points to an allowed regular file, and satisfies applicable size and content constraints. These are safe reference-resolution rules, not part of the interchange vocabulary.

## Guiding test

A valid Work Products section answers:

> What file-based things have the workflow steps produced, what are they, and how do they relate?

It does not answer:

> Which step runs next, or what must that step do with them?

