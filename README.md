# agentic-team-kit

Claude Code skills for running a small "agent development team" over a codebase: an indexer that
onboards agents onto an existing repo, and a chain of read-work skills — product manager,
architect, dev manager, QA — that turn a feature request into an approved plan and a failing
test suite before any code gets written.

## Skills

| Skill | Purpose |
|---|---|
| [`repo-indexer`](.claude/skills/repo-indexer/SKILL.md) | Reads an existing repository and produces `.agentteam/repo-map.md` and a draft `.agentteam/company.md` — the context files every other agent depends on. |
| [`pm-requirements`](.claude/skills/pm-requirements/SKILL.md) | Turns a short feature request into `docs/features/<slug>/requirements.md`: use cases, edge cases, testable acceptance criteria, and one batched list of open questions. |
| [`architect-design`](.claude/skills/architect-design/SKILL.md) | Turns `requirements.md` into `design.md`: components, data model, interfaces, conventions followed/deviated, and the architect's share of the same open-question batch. |
| [`dev-task-split`](.claude/skills/dev-task-split/SKILL.md) | Turns `design.md` into `tasks.json`: an ordered task list with explicit file ownership, so parallel work is only ever attempted when disjoint file sets prove it's safe. |
| [`qa-test-plan`](.claude/skills/qa-test-plan/SKILL.md) | Turns an *approved* `requirements.md` into a failing test suite, one test per acceptance criterion — a dev agent's exit condition, never a prose bug report. |

## The orchestrator

`orchestrator/` is the write-work half: plain Python, no model in the loop. It reads a
task plan and decides what may run concurrently — and refuses the plan when that can't be
established.

```console
$ python3 -m orchestrator validate docs/features/dark-mode/tasks.json
T1 and T2 both own overlapping paths ('src/api/**' ∩ 'src/api/users.ts') but neither depends on the other

$ python3 -m orchestrator schedule docs/features/dark-mode/tasks.json
dark-mode: 4 tasks in 3 wave(s), max concurrency 2 (mode: parallel)

  wave 0 (parallel):
    T1  Theme tokens + provider
      owns:     src/theme/**
      worktree: .worktrees/dark-mode-t1  branch: agent/dark-mode-t1
    ...
```

Both commands exit non-zero on an unsafe plan, so this belongs in CI between
`dev-task-split` and any agent writing code.

- **Glob intersection is exact, not filesystem-based.** Two `owns` globs are compiled to
  NFAs and walked as a product automaton, so the check covers files a task will *create* —
  which are the ones that actually collide. Expanding globs against files already on disk
  would miss them entirely.
- **Waves are derived, not declared.** Tasks share a wave only when the DAG puts no edge
  between them, and validation has already proven no-edge implies no shared files. `mode`
  can narrow the schedule but never widen it past what the globs allow.
- **Spec Kit plans import too.** `tasks.md` is read as a lossy import: file ownership is
  recovered from the task description, non-`[P]` tasks are treated as phase barriers, and
  a task naming no file is given `**` so it is scheduled alone rather than assumed safe.

## Running the dev agents

`orchestrator run` executes the schedule: a git worktree per task, agents in parallel
within a wave, tests as the exit condition.

```console
$ python3 -m orchestrator init          # writes .agentteam/config.json
$ python3 -m orchestrator run docs/features/dark-mode/tasks.json

wave 0: T1, T2
  T2 round 1: pass
  T1 round 1: pass

wave 1: T3
  T3 round 1: pass

dark-mode: 3/3 tasks ok on agent/integration
```

**The agent is a command template, not an SDK.** Nothing here imports a vendor library —
the runner renders a command and runs it as a subprocess, so the same task plan drives
Claude Code, Cursor, Antigravity, Codex or a shell script, and switching is a config edit:

```json
{
  "agent":  { "preset": "claude", "timeout_seconds": 1800 },
  "verify": { "command": ["python3", "-m", "pytest", "-q"] },
  "policy": { "max_rounds": 3, "max_concurrency": 4 }
}
```

Presets: `claude`, `cursor`, `codex`, `gemini`, `echo`. Anything else goes in `command` as
argv parts, one containing `{prompt}`.

How a task finishes:

| Status | Meaning |
|---|---|
| `completed` | verification passed, merged into the integration branch |
| `held` | verification passed, but `requires_human_review` withheld the merge |
| `failed` | rounds exhausted with tests still failing |
| `conflicted` | verified, but would not merge — something outside `owns` was touched |
| `errored` | the agent could not be run (missing CLI, timeout) |
| `skipped` | an earlier wave stopped the run |

- **Tests decide, not the agent.** A task is done when the verification command exits
  zero. With no `verify.command` configured the run is refused rather than assumed
  passing — there would be no way to tell whether anything worked.
- **Failure output goes back into the next round's prompt**, bounded by `max_rounds`. A
  missing agent binary errors immediately instead of burning every round on the same
  error.
- **Merges happen after the whole wave finishes**, never as each agent lands, so the
  integration branch does not move under the others. A conflict there is a finding, not
  routine: disjointness was already proven, so it means something outside `owns` was
  edited — a lockfile, a generated file, a shared registry.

See [`docs/spec-kit-evaluation.md`](docs/spec-kit-evaluation.md) for how this compares to
GitHub Spec Kit's `implement` step.

```console
$ python3 -m unittest discover -s tests
```

The runner's tests use a shell script as the agent, so the whole loop — worktrees, rounds,
verification, merge — is covered without an API key or a network.

## How they fit together

This is read work vs. write work: everything below is read work (independent analyses that merge
fine) and runs before a human approval gate. Write work — dev agents implementing tasks — comes
after the gate and isn't covered by this kit yet.

1. **`repo-indexer`** (once per repo) → `.agentteam/repo-map.md` + `.agentteam/company.md`. On
   brownfield these are extracted from the code and reviewed by a human; on greenfield the
   indexer interviews the human for `company.md` and defers the repo map to feature one.
2. **`pm-requirements`** (per feature) → `docs/features/<slug>/requirements.md`. Reads
   `company.md` and `repo-map.md`, grounds every use case in real paths, ends with a numbered,
   batched list of open questions (`Qn`).
3. **`architect-design`** → `docs/features/<slug>/design.md`. Reads `requirements.md` and the
   actual code, designs components/data model/interfaces against the existing conventions, and
   continues the same `Qn` batch rather than starting a new one.
4. **`dev-task-split`** → `docs/features/<slug>/tasks.json`. Reads both docs above, splits the
   design into tasks with narrow `owns` globs. Any two tasks with overlapping globs must have an
   explicit `depends_on` edge; the default is sequential execution, not parallel — parallelism is
   only used where disjointness was actually verified.
5. **Gate (human).** All open questions from steps 2–3 are answered once, in one batch; the human
   approves `requirements.md`, `design.md` and `tasks.json` together.
6. **`qa-test-plan`** (after the gate) → a failing test per acceptance criterion, plus
   `docs/features/<slug>/test-manifest.json` mapping `AC-n` → test. This is also how QA reports
   bugs mid-loop later: a new failing test, never a written description.
7. **`orchestrator`** validates `tasks.json`, schedules it into waves, and runs the dev
   agents against it — worktree per task, tests as the exit condition, bounded retries,
   merge on green. A QA-run step that maps `AC-n` to pass/fail, and a reviewer that turns
   the diff into a PR description, are the remaining write-work phases.

## Layout

```
.claude/skills/
  repo-indexer/
    SKILL.md
    scripts/scan.py              # deterministic repo scan: languages, manifests, CI, tests, secrets
    references/conventions-checklist.md
    templates/repo-map.md        # copied to <target-repo>/.agentteam/repo-map.md
    templates/company.md         # copied to <target-repo>/.agentteam/company.md
  pm-requirements/
    SKILL.md
    references/artifact-schema.md   # the requirements.md contract
  architect-design/
    SKILL.md
    references/design-schema.md     # the design.md contract
  dev-task-split/
    SKILL.md
    references/tasks-schema.md      # the tasks.json contract (read by the orchestrator, not just agents)
  qa-test-plan/
    SKILL.md
    references/test-manifest-schema.md  # the test-manifest.json contract

orchestrator/
  globset.py    # exact glob intersection (NFA product) — the `owns` collision test
  model.py      # Task / Plan, and the invariants that make a plan well-formed
  parse.py      # tasks.json, plus a lossy import of Spec Kit's tasks.md
  validate.py   # overlapping owns without a dependency edge = refuse to run
  schedule.py   # waves, worktrees, branches
  worktree.py   # git worktree lifecycle + merge-back
  agent.py      # command-template agent invocation, and the dev-agent brief
  config.py     # .agentteam/config.json — which agent, which tests, how many rounds
  runner.py     # the wave loop: dispatch, verify, retry, merge
  cli.py        # python -m orchestrator validate|schedule|run|init

tests/
  test_orchestrator.py   # planning: globs, validation, scheduling, parsing
  test_runner.py         # execution, with a shell script standing in for the agent
```

## Repository context files

Both skills read and write `.agentteam/repo-map.md` and `.agentteam/company.md` in the *target*
repository (not in this kit). `repo-map.md` records where things live and how to build/test it;
`company.md` records domain, users, business rules and standards. Neither file should ever
contain credentials, connection strings, or customer data — they are committed and get read
straight into agent prompts.
