# Architecture Hygiene

Klara's architecture docs are working memory, not a junk drawer. They should be
cleaned at predictable points so the curriculum stays readable.

## Source Of Truth Order

Use this order when documents disagree:

1. `docs/architecture/klara-technical-roadmap.md`
2. `docs/architecture/klara-future-folder-map.md`
3. current chapter docs under `docs/chapters/`
4. reference synthesis documents
5. old discovery notes or reports

If a lower-priority document contains a better decision, promote the decision
upward and mark or remove the stale text.

## Architecture Directory Shape

Keep `docs/architecture/` small:

```text
docs/architecture/
  klara-technical-roadmap.md
  klara-future-folder-map.md
  klara-reference-synthesis.md
  klara-coding-conventions.md
  architecture-hygiene.md
  ch01-minimal-loop-spec.md
```

Chapter-specific implementation teaching belongs in:

```text
docs/chapters/
```

Historical reports, audits, experiments, and one-off comparisons should move
out of architecture when they stop being active decisions.

Recommended archive path:

```text
docs/archive/YYYY-MM-DD/<slug>.md
```

## Cleanup Cadence

Run an architecture cleanup after:

- finishing a chapter
- changing folder boundaries
- introducing a new runtime layer
- deleting or renaming public concepts
- before merging a branch back into the main Klara route

## Cleanup Checklist

1. Read the roadmap and chapter doc together.
2. Remove duplicate route descriptions.
3. Promote current decisions into the roadmap or folder map.
4. Move old discovery material into `docs/archive/`.
5. Check that README links only to active documents.
6. Check that code names match documented names.
7. Check that tests protect the most important boundary claims.

## Stale Document Signals

A document should be cleaned, merged, or archived when:

- it says "maybe" about something already decided
- it repeats the roadmap in older wording
- it describes a folder that no longer exists
- it gives Chapter 1 responsibilities to a later chapter
- it treats RAG, memory, skills, routines, or UI as core loop concerns

## Deletion Rule

Delete or archive stale architecture docs. Do not keep every draft in the active
architecture directory.

If a stale document has one useful paragraph, move that paragraph into the
current source-of-truth document and archive the rest.

## Review Question

At the end of each chapter, ask:

> If a new reader opened this repository today, would the architecture folder
> show the current route, or the history of our confusion?

The answer should be "current route."
