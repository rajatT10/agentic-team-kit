# design.md schema

The contract between the architect and the dev manager (and, downstream, every dev agent). Keep
the headings exactly as written — they are load-bearing.

## Template

```markdown
---
feature: <slug>
status: draft | approved
mode: brownfield | greenfield
created: <YYYY-MM-DD>
requirements: docs/features/<slug>/requirements.md
---

# <Feature name> — Design

## Approach

<One paragraph. The technical approach at a systems level.>

## Components

| Component | New / Existing | Path | Responsibility | Covers |
|---|---|---|---|---|
| <name> | new | `<path>` | <one line> | UC-1 |
| <name> | existing | `<path>` | <one line> | UC-2, EC-1 |

## Data model

| Entity | Change | Storage | Backfill needed? |
|---|---|---|---|
| <entity> | <add field / new table / ...> | <db/table> | yes / no — <why> |

_Omit this section entirely if the feature has no data model changes; say so in one line instead
of leaving an empty table._

## Interfaces

| Interface | Kind | Shape | Consumed by |
|---|---|---|---|
| `<path/route/signature>` | new / changed | <request/response or signature, brief> | <component or UC> |

## Conventions

| Convention | Followed how | Example / reason |
|---|---|---|
| <convention name> | followed | `<path that demonstrates it>` |
| <convention name> | **deviation** | <why the existing pattern doesn't fit here> |

## Risks and tradeoffs

- <risk> — <mitigation or accepted cost>

## Out of scope

- <item> — <why deferred>

## Open questions

| # | Question | Placeholder assumption | Blocking |
|---|---|---|---|
| Qn+1 | <question> | <what the team proceeds with if unanswered> | yes / no |
```

## Rules for each section

**Approach** — systems-level, not implementation detail. What moves, what's added, what's
removed. A reader who has never seen the codebase should understand the shape of the change.

**Components** — `Covers` must name at least one `UC-n` or `EC-n` from `requirements.md`. A
component with no `Covers` entry is scope creep, not design. `Path` must be real for `existing`
rows (verified by reading the file) and must follow the established directory layout convention
for `new` rows.

**Data model** — high-level only: what changes, not a full field-by-field migration. That detail
belongs in the dev agent's implementation, not the design doc, where it would go stale. Backfill
column exists specifically to cross-check the PM's "existing data written before this feature
existed" edge case.

**Interfaces** — shape means enough to implement against, not a full OpenAPI spec: key
request/response fields or a function signature, not every parameter.

**Conventions** — every row is either `followed` with a citation, or `deviation` with a reason.
There is no third state. An uncited convention is not recorded as followed.

**Risks and tradeoffs** — two or three sentences per row. This section is read by a human at the
gate; keep it that short or it won't be read.

**Out of scope** — design-level exclusions, distinct from (and additive to) the PM's out-of-scope
section. Never claim something is out of scope if `requirements.md` listed it as a use case —
that's a question back to the PM, not a unilateral cut.

**Open questions** — continues the `Qn` numbering from `requirements.md`. Never restarts at `Q1`.
Same placeholder-assumption and blocking rules as the PM schema.

## Naming

- IDs referenced from `requirements.md` (`UC-n`, `EC-n`) are never renumbered here — only cited.
- New question IDs continue the sequence: if `requirements.md` ends at `Q4`, this document's
  first new question is `Q5`.
