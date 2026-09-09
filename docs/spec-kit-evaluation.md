# Spec Kit evaluation

Evaluated at commit `f21acc4` of `github/spec-kit`, by reading the shipped command
templates, the workflow engine and the extension system rather than the documentation.

The question: build the spec chain ourselves, or extend Spec Kit?

**Answer: extend it.** Spec Kit already solves the parts of this kit that are expensive
and undifferentiated — portability across 30+ agents, the CLI, the templates, the human
gates. It does not solve the three things this kit exists for.

## What Spec Kit already has

| Capability | Detail |
|---|---|
| Command chain | `specify` → `plan` → `tasks` → `implement`, plus `clarify`, `analyze`, `checklist`, `converge`, `constitution`, `taskstoissues` |
| Workflow engine | Typed steps: `gate`, `fan-out` (bounded thread pool, `max_concurrency`), `do_while`, `while_loop`, `if_then`, `switch`, `shell`, `command`, `prompt`, `slot`, `init` |
| Human gates | `type: gate` with `options: [approve, reject]` and `on_reject: abort` |
| Extension system | `.specify/extensions.yml`, with `before_*` / `after_*` hooks on all ten commands, plus a community catalog |
| Bug workflow | A `bug` extension: `assess` → `fix` → `test` |
| Reach | 30+ integrations, MIT licensed |

Rebuilding this from scratch would cost months and land somewhere worse.

## What it does not have

### 1. Machine-checkable file ownership

Spec Kit's task format is a markdown checklist:

```text
- [ ] T005 [P] Implement authentication middleware in src/middleware/auth.py
```

The `[P]` marker means "parallelizable". Its own template defines the rule as *"include
ONLY if task is parallelizable (different files, no dependencies on incomplete tasks)"* —
a judgement the generating model makes in prose, with the file path embedded in the task
description. **Nothing verifies it.** Two `[P]` tasks that both touch `src/api/` are
indistinguishable from two that don't.

This kit's `tasks.json` states ownership as globs in a dedicated `owns` field, and the
orchestrator refuses to run a plan where two unordered tasks' globs intersect. That check
is the difference between a parallelism hint and a parallelism guarantee.

2026 research is unambiguous about why this matters: cross-agent merge conflicts occur at
roughly twice the rate of intra-agent conflicts.

### 2. Isolated parallel execution

The shipped `speckit` workflow is linear:

```yaml
specify → gate(review-spec) → plan → gate(review-plan) → tasks → implement
```

`implement` is a single agent working the checklist top to bottom. It is told that "[P]
tasks can run together", but there are no worktrees, no branch isolation and no dispatch
to separate agents. The `fan-out` primitive that would enable this exists in the engine
and the shipped workflow never uses it.

### 3. Tests as the exit condition

Spec Kit's checklists are *requirements-quality* gates — `[x]` means a reviewer judged a
criterion well-written, explicitly **not** that implementation is complete. Completion
validation is prose: "validate that tests pass and coverage meets requirements".

There is no acceptance-criterion → test mapping, so a dev agent's exit condition is a
model's opinion that it is done. The `bug` extension is closer, but it triages reported
bugs; it does not turn an AC into a failing test up front.

### Retry behaviour

`implement` halts on a failed sequential task and, for `[P]` tasks, "continues with
successful tasks, reports failed ones". There is no re-dispatch, no bounded retry, no
escalation policy. `do_while` and `converge` exist as primitives to build one.

## Recommendation

| Layer | Owner |
|---|---|
| Spec chain, gates, CLI, agent portability | Spec Kit — adopt as-is |
| `owns` globs + collision refusal | This kit — `orchestrator/` |
| Worktree-isolated parallel dev agents | This kit — a workflow using `fan-out` |
| AC → failing test manifest, bug-as-test | This kit — an extension |

The integration point is `.specify/extensions.yml`: a `before_implement` hook can hand the
plan to `orchestrator validate` and abort before any agent writes, and a custom
`workflow.yml` can replace the linear `implement` step with a fan-out over waves.

Estimated effort to extend: weeks. Estimated effort to rebuild: months.
