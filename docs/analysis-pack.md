# Analysis Pack — Recurring Deep-Dive Review Task
# Version: analysis-pack.txt

---

## STEP 1 — DETERMINE OUTPUT FOLDER (Do this before any other work)

Before reading a single source file, before writing a single review, execute this exact algorithm:

1. Set BASE = `docs/reviews/<today's date as yyyy-mm-dd>`
2. If `BASE` does NOT exist → create it. OUTPUT_DIR = BASE. Done.
3. If `BASE` EXISTS:
   a. Check for `BASE-1`, `BASE-2`, … up to `BASE-99`.
   b. Find the highest-numbered versioned folder that already exists (or 0 if none).
   c. Set OUTPUT_DIR = BASE-(N+1).  Create it.
4. Confirm OUTPUT_DIR by printing: "Output folder: docs/reviews/<OUTPUT_DIR>"

IMMUTABILITY RULE: You MUST NEVER add files to, modify files in, or delete files from any folder
other than OUTPUT_DIR. Existing review folders are sealed archives. They document past states of the
codebase. They are not drafts to be completed.

---

## STEP 2 — READ THE GROUND-TRUTH BASELINE (Before writing any review)

The same verification discipline applies to negative assertions. Before stating that a feature,
page, or capability is ABSENT from the product, you MUST look for it in the codebase. The gap
between "I didn't see it" and "it does not exist" is equally dangerous.

---

## STEP 3 — PRODUCE ALL REVIEWS (Fresh, every run, in OUTPUT_DIR)

Write each of the following reviews to OUTPUT_DIR/<nn>-<slug>.md. All 16 are mandatory every run.
Do not skip any. Do not reuse content from prior review cycles. Read the current state of the
codebase for each review — do not rely on prior reviews' findings.

[FIX-3: OUTPUT FILE FORMAT — READ THIS CAREFULLY:

Every review file MUST be a Markdown file with a .md extension. No other format is permitted.
Specifically:
- Do NOT produce .pdf files. The review task does not call for PDFs and no tooling to create
  them is implied. If you find yourself writing to a .pdf path, STOP — you have misread these
  instructions.
- Do NOT produce .txt files. Same rule applies.
- The file names are exactly as shown in the numbered list below (e.g., "01-security-audit.md").
  Do NOT append a version number or date suffix to individual review file names (e.g., do NOT
  write "01-security-audit-1.md" or "01-security-audit-2026-03-04.md"). Version identity is
  carried by the OUTPUT_DIR folder name, not by the review filenames within it.

Why these failures occurred in the prior run: The model produced .pdf and .txt variants and
appended version numbers to file names despite none of these behaviors being specified or implied
by the instructions. The most likely cause is pattern-matching on conventions seen in other
contexts (e.g., generating PDFs when producing "formal" documents, appending version suffixes as
a general cautious habit). These behaviors are incorrect here and must not recur. The instructions
are explicit: .md files only, named exactly as shown below.]

01. Security audit/review → 01-security-audit.md
02. Legal and regulatory compliance review → 02-legal-compliance.md
03. Brand and IP Audit → 03-brand-ip-audit.md
04. Test coverage review → 04-test-coverage.md
05. Code quality review → 05-code-quality.md
06. Technical due diligence review → 06-tech-due-diligence.md
07. Accessibility review → 07-accessibility.md
08. Architecture review → 08-architecture.md
09. Scalability review → 09-scalability.md
10. Operational practice review → 10-operational-practice.md
11. Data & Privacy Compliance review → 11-data-privacy-compliance.md
12. Third-Party & Open-Source license audit → 12-license-audit.md

In each case assume the role of an expert analyst/reviewer of the relevant topic area with a careful
eye for detail. Assume you are evaluating the asset from the perspective of a potential buyer.

You MUST NOT rely on any planning documents.  Many planning
documents are obsolete, contain already-completed work, hallucinated work, or work that will never be
done. Rely on the actual code. Use completed.md and the git commit log only for historical context.

---

## STEP 4 — PRODUCE workplan.md (after all reviews are complete)

After all reviews are written to OUTPUT_DIR, write OUTPUT_DIR/workplan.md.

[FIX-4: WORK ITEM FORMAT — READ THIS CAREFULLY BEFORE WRITING A SINGLE WORK ITEM:

Every work item in workplan.md MUST include ALL of the following five fields. A work item that is
missing any field is malformed and must not appear in the output.

  Slug:     A unique, stable kebab-case identifier for this item. Format: <domain>-<verb>-<noun>
            (e.g., "sec-remove-unsafe-eval", "legal-finalize-docs", "ops-add-cicd-pipeline").
            Rules for slugs:
            - MUST be unique across the entire workplan — no two items may share a slug.
            - MUST NOT contain phase numbers, dates, or run-specific identifiers.
            - MUST be stable: if this item appears in a future run's workplan, the same slug
              should be used so progress can be tracked across runs.
            - MUST be usable as a git branch name (lowercase, hyphens only, no spaces).

  Priority: The severity level of the originating finding, copied verbatim from the review.
            MUST be exactly one of: HIGH | MEDIUM | LOW
            This field MUST match the severity table entry in the source review. Do NOT assign a
            priority based on the item's phase position. Do NOT promote or demote the priority
            relative to what the review stated. If two findings of different severities are
            combined into one work item, use the higher severity.

  Source:   The originating review file and the exact heading of the finding that generated this
            item. Format: <review-filename.md> — "<finding heading as written in the review>"
            Example: 01-security-audit.md — "MEDIUM — `unsafe-eval` in production CSP"
            If a work item consolidates findings from multiple reviews, list all sources,
            one per line, each prefixed with "Source:".

  Done when: A single, concrete, objectively verifiable acceptance criterion. Must not use vague
             language like "it works" or "it is improved." Must describe a state that can be
             confirmed by running a command or making an observation.

  Commit:   The git commit message to use when this item is complete. Must follow the project's
            conventional commit style (e.g., "security: ...", "data: ...", "legal: ...").

In addition to the per-item fields above, each item MUST also include the file paths and concrete
code changes that were already required in analysis-pack-3.

REQUIRED ITEM FORMAT — use exactly this layout for every work item:

  **<slug>** · Priority: <HIGH|MEDIUM|LOW>
  Source: <review-filename.md> — "<finding heading>"
  - Files: <specific file paths>
  - Changes: <concrete description of the code or configuration change>
  - Done when: <objective acceptance criterion>
  - Commit: `<conventional commit message>`

Why this format was absent in analysis-pack-3: Step 4 listed four required fields (file paths,
code changes, "done when", commit message) but did not list slug or priority as required fields.
The workplan produced by the 2026-03-05 run used positional labels (1a, 1b, 2a, ...) as item
identifiers instead of stable slugs, and assigned priority implicitly through phase grouping
rather than by citing the severity level from the originating review finding. This meant:

  (1) No work item had a stable identifier. If phases are reordered, items added, or items
      skipped, the positional label changes. There is no way to say "item 2a from last run is
      now 3a" — the identity of the item is lost.

  (2) No work item had a machine-readable priority field. A reader of the workplan could not
      filter items by priority, sort them, or verify that the phase ordering was consistent
      with the review severities, because the priority was embedded only in the phase header
      ("Phase 1 — Critical") rather than stated per-item.

  (3) No work item cited its source. A reader could not verify which review produced a given
      work item, could not check whether the review finding had been resolved by a subsequent
      code change, and could not trace "this commit closes this finding in this review cycle."

These three gaps made the workplan less useful as a tracking document and incompatible with
future automation (e.g., generating tickets, tracking completion across runs). Step 4 now
requires all five fields on every item.]

workplan.md structure:

- Header: run date, OUTPUT_DIR path, note that this is a read-only output document.
- Prioritized implementation phases: items grouped into ~20-minute phases, sequenced so that
  HIGH-priority items appear before MEDIUM items, and MEDIUM before LOW. Within a phase, items
  may be sequenced for logical dependency (e.g., a migration before the route change that uses it).
  Each item MUST use the five-field format defined above.
- Additional reviews section: recommendations for review areas identified as needing deeper
  investigation in the next cycle.
- Session restart prompt (see Step 5).

workplan.md is an OUTPUT of this review process, not a living document to be edited. If you need to
work through the phases, treat workplan.md as read-only instructions and track phase completion
separately in `docs/planning/todo.md` or via git commits, NOT by editing workplan.md.

---

## STEP 5 — SESSION RESTART PROTOCOL

This task typically spans multiple sessions. To resume a partially completed run:

**Resume prompt (copy this verbatim into a new session):**

> Continue the analysis pack. Read `docs/planning/analysis-pack-4.txt` for task
> instructions. Then check `docs/reviews/` to find the most recent OUTPUT_DIR (highest version for
> today, or today's base folder). List its contents. Write any reviews from the 16-review list that
> are not yet present. When all 16 reviews exist, write or complete workplan.md. Do NOT create a new
> versioned folder — you are resuming an in-progress run, not starting a new one.

**How to identify an in-progress run vs. a completed run:**
- A run is COMPLETE if OUTPUT_DIR contains all review files AND workplan.md.
- A run is IN PROGRESS if OUTPUT_DIR exists but is missing one or more of the above.
- If the most recent folder is complete, a new invocation MUST create a new versioned folder (Step 1).

---

## STEP 6 — RUNNING THIS TASK REPEATEDLY

This task is designed to be run multiple times per day against the evolving codebase. Each run:

- Produces a complete, independent snapshot of the codebase's review state at that moment.
- Never modifies any prior run's output.
- Is identified by its versioned folder name (e.g., 2026-03-04-3 is the third run on March 4).

To start a fresh run: paste the contents of this file as your task prompt. Step 1 will automatically
determine the correct new output folder.

To resume an interrupted run: use the resume prompt in Step 5.

---

## APPENDIX — KNOWN FAILURE MODES (for reference)

This appendix documents specific errors from prior runs so they are not repeated.


### Failure Mode 3 — Reusing prior-cycle findings without re-reading the code

**What went wrong (original cycle):** Reviews were partially copied or assumed to be valid from a
prior cycle rather than regenerated from the current codebase. This caused both false positives
(already-fixed issues reported as open) and false negatives (new regressions missed).

**How to avoid:** Step 3 mandates fresh reads of the codebase for every review in every run. Prior
OUTPUT_DIR contents are sealed archives to be ignored during review writing.

### Failure Mode 4 — Producing .pdf and .txt output files instead of .md

**What went wrong (2026-03-04-2):** Review files were written as .pdf and/or .txt files in
addition to, or instead of, .md files. The instructions have always specified .md exclusively.

**Root cause:** The model pattern-matched on conventions from other contexts — generating PDFs for
"formal" documents, or producing .txt as a lowest-common-denominator format — without grounding
the decision in what the instructions actually specify. The explicit ".md" extension stated in
Step 3 was not respected.

**How to avoid:** Step 3 now includes an explicit prohibition on .pdf and .txt output with a
direct explanation of why these formats are wrong here. If you are about to write to a non-.md
path inside OUTPUT_DIR, stop and re-read Step 3 before proceeding.

### Failure Mode 5 — Appending version numbers to individual review file names

**What went wrong (2026-03-04-2):** Review files were named with version suffixes (e.g.,
`01-security-audit-1.md`, `02-legal-compliance-2.md`) that were not requested and do not appear
in the instructions.

**Root cause:** The model applied a general cautious versioning habit to file names that are
already versioned at the folder level (OUTPUT_DIR). This created redundant and incorrect naming.

**How to avoid:** Version identity is carried entirely by the OUTPUT_DIR folder name. Review file
names within OUTPUT_DIR are fixed and must match exactly the list in Step 3. Do not append any
suffix to individual review file names.

### Failure Mode 6 — Asserting features are absent without verifying in the codebase
**Root cause:** The reviewer did not search the codebase before asserting absence. Negative claims
("this feature does not exist") require the same evidentiary standard as positive claims. "I did
not recall seeing it" is not evidence of absence.

**How to avoid:** Step 2 now mandates reading the relevant files before writing the legal review.
The general rule in Step 2 has been extended to cover negative assertions: before asserting any
feature or control is MISSING, search for it. Step 3 reinforces this with an explicit reminder.

### Failure Mode 7 — workplan.md items missing slug, priority, and source citation

**What went wrong (2026-03-05):** The workplan.md produced by the first run under analysis-pack-3
used positional phase labels (1a, 1b, 2a, ...) as item identifiers instead of stable slugs. No
item carried an explicit Priority field. No item cited its source review file or finding heading.

**Root cause:** Step 4 of analysis-pack-3 listed four required per-item fields (file paths, code
changes, "done when", commit message) but did not list slug, priority, or source citation as
required fields. The model complied with the spec as written. Items were implicitly prioritized
through phase grouping (Phase 1 = critical, Phase 2 = high, etc.) rather than explicitly on each
item. This encoding of priority in the phase header rather than the item record meant:

  (1) Removing or reordering phases destroyed the priority record for all affected items.
  (2) A reader could not filter or sort items by priority without parsing phase headers.
  (3) No item could be traced back to the specific finding and review that generated it.
  (4) Cross-run progress tracking was impossible: the same underlying issue would have a
      different label (e.g., "2a" vs. "3a") in different workplan runs.

**How to avoid:** Step 4 now requires all five fields — slug, priority, source, "done when", and
commit — on every work item, in a defined layout. The [FIX-4] block in Step 4 explains this in
detail and documents the exact required format. Before writing any work item, check that it
contains all five fields. If any field is missing, the item is malformed and must be corrected
before the workplan is written.
