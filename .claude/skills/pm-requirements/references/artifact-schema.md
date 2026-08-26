# requirements.md schema

This is the contract between the product manager and every downstream agent. The architect, the
dev manager and the QA manager all parse this file. Keep the headings exactly as written — they
are load-bearing.

## Template

```markdown
---
feature: <slug>
status: draft | approved
mode: brownfield | greenfield
created: <YYYY-MM-DD>
---

# <Feature name>

## Summary

<One sentence. What the user can do after this ships that they could not do before.>

## Users

| Role | Involvement |
|---|---|
| <role from company.md> | <triggers / affected / administers> |

## Use cases

### UC-1: <short goal-shaped title>

**Actor:** <role>
**Touches:** `<path/to/module>`, `<path/to/other>`
**Flow:**
1. <step>
2. <step>

### UC-2: ...

## Edge cases

### EC-1: <condition>

**Applies to:** UC-1
**Expected behaviour:** <what should happen>

### EC-2: ...

## Acceptance criteria

| ID | Covers | Given | When | Then |
|---|---|---|---|---|
| AC-1 | UC-1 | <starting state> | <action> | <observable outcome> |
| AC-2 | EC-1 | ... | ... | ... |

## Out of scope

- <item> — <why excluded>

## Open questions

| # | Question | Placeholder assumption | Blocking |
|---|---|---|---|
| Q1 | <question> | <what the team proceeds with if unanswered> | yes / no |
```

## Rules for each section

**Summary** — one sentence, user-facing outcome. Not "add a table", but "a user can export their
invoices as CSV".

**Users** — roles must come from `company.md`. If the role does not exist there, that is a
question, not a new role you invent.

**Use cases** — `Touches` is mandatory in brownfield mode and must contain real paths you
verified by reading the repository. A use case with no verified path is not a use case yet; it is
a question. In greenfield mode, write `Touches: greenfield`.

**Edge cases** — each links to the use case it modifies. Edge cases that do not change behaviour
(they are already handled correctly today) still get recorded, with the expected behaviour
stated, so QA writes a regression test rather than assuming.

**Acceptance criteria** — the most important section, because it is executable downstream.

- One row per use case, plus one per behaviour-changing edge case
- `Given` is a concrete starting state, not a mood: "a user with three saved invoices", not "a
  logged-in user"
- `Then` is observable from outside the system: a response body, a database row, a visible
  element, an emitted event. Never "the system knows" or "the state is correct"
- No criterion may contain "and" joining two outcomes — split it into two rows
- Every row must be turnable into a failing test without a human deciding what it meant

**Out of scope** — never empty. If nothing was excluded, the feature was not scoped.

**Open questions** — numbered, each with a placeholder so unanswered non-blocking questions do
not stall the pipeline. `Blocking: yes` means the architect cannot start. Use it sparingly; if
everything is blocking, the request was too vague to spec and should go back to the requester.

## Naming

- Feature slug: kebab-case, matches the directory and the eventual branch name
- IDs: `UC-n`, `EC-n`, `AC-n`, `Qn` — referenced by every downstream artifact, so they must be
  stable. Never renumber an existing ID when revising; append new ones.
