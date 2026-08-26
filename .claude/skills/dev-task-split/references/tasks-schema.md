# tasks.json schema

The contract between the dev manager and the orchestrator. Unlike the other artifacts, this one
is read by deterministic code, not by an LLM agent interpreting prose — field names and types are
load-bearing in the strictest sense: a typo here is a runtime error, not a misunderstanding.

## Template

```json
{
  "feature": "<slug>",
  "requirements": "docs/features/<slug>/requirements.md",
  "design": "docs/features/<slug>/design.md",
  "mode": "sequential",
  "tasks": [
    {
      "id": "T1",
      "title": "<short goal-shaped title>",
      "covers": ["UC-1", "AC-1", "AC-2"],
      "owns": ["path/to/module/**", "path/to/other-file.ts"],
      "depends_on": [],
      "requires_human_review": false,
      "notes": "<why sequential/parallel, why this grouping, anything the dev agent should know that isn't in design.md>"
    },
    {
      "id": "T2",
      "title": "<short goal-shaped title>",
      "covers": ["UC-2"],
      "owns": ["path/to/other-module/**"],
      "depends_on": ["T1"],
      "requires_human_review": false,
      "notes": ""
    }
  ]
}
```

## Field rules

**`mode`** — `"sequential"` or `"parallel"`. Applies to the whole task list, not per-task. A task
list is only `"parallel"` if every task pair without a `depends_on` edge has been verified to have
zero `owns` overlap and zero data dependency. The orchestrator is expected to enforce
non-overlap regardless of what this field says — it is documentation of intent, not the safety
mechanism.

**`tasks[].id`** — `T1`, `T2`, ... in the order the dev manager produced them. Referenced by
`depends_on`; never renumbered once QA or a dev agent has started referencing it. Append new
tasks with new IDs if the plan changes after work has started.

**`tasks[].covers`** — real IDs from `requirements.md` (`UC-n`, `EC-n`, `AC-n`) only. This is what
lets the QA agent's failing tests (one per `AC-n`) be matched back to the task that should make
them pass.

**`tasks[].owns`** — glob patterns, as narrow as accurately describes the files this task
creates or modifies. This is the field the orchestrator uses to detect conflicts: **any two tasks
whose `owns` globs overlap must appear in each other's dependency chain**, directly or
transitively. A dev-task-split output where this isn't true is invalid and should be rejected by
the orchestrator before any dev agent runs, not discovered after a merge conflict.

**`tasks[].depends_on`** — task IDs that must complete (and pass QA) before this task starts.
Forms a DAG; the orchestrator topologically sorts it. A cycle is invalid input.

**`tasks[].requires_human_review`** — `true` when the task's `owns` glob intersects a
`repo-map.md` danger zone. The orchestrator pauses before merging this task's output, regardless
of test results, until a human reviews it.

**`tasks[].notes`** — free text for context that doesn't fit another field: why this task is
grouped the way it is, why the list is (or isn't) parallel, anything a dev agent reading only this
task and `design.md` would otherwise be missing. Empty string is valid; omit only if your tooling
requires the key to be present with a value.

## Orchestrator contract

The orchestrator (a plain state machine, not an LLM) is responsible for:

- Validating that no two tasks with overlapping `owns` have a missing `depends_on` edge, and
  refusing to run the plan if one is found — this validation is what makes the dev manager's
  hard rules enforceable rather than aspirational.
- Running tasks in dependency order; running independent tasks concurrently only when `mode` is
  `"parallel"`.
- Pausing on any task with `requires_human_review: true` before merging its output.
- Enforcing the dev↔QA round limit per task (recommended default: 3 rounds, then escalate to a
  human) and a wall-clock / token budget per feature — these limits live in the orchestrator's
  config, not in `tasks.json`, because they're operational policy, not part of the task plan.

## Naming

- Feature slug matches the one used in `requirements.md` and `design.md`.
- Task IDs: `T1`, `T2`, ... — stable once referenced, never renumbered, only appended to.
