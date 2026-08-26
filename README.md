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
7. Dev agents, a QA-run step, and a reviewer that turns the diff into a PR description are the
   write-work phases that consume the above — not covered by this kit yet.

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
```

## Repository context files

Both skills read and write `.agentteam/repo-map.md` and `.agentteam/company.md` in the *target*
repository (not in this kit). `repo-map.md` records where things live and how to build/test it;
`company.md` records domain, users, business rules and standards. Neither file should ever
contain credentials, connection strings, or customer data — they are committed and get read
straight into agent prompts.
