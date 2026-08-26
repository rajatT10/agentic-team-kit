# test-manifest.json schema

The contract between the QA manager and the orchestrator/dev agent. It is what lets the
orchestrator answer "did task T2 pass QA?" by running a command and reading an exit code, instead
of an LLM re-reading a prose report.

## Template

```json
{
  "feature": "<slug>",
  "requirements": "docs/features/<slug>/requirements.md",
  "framework": "<test framework name, e.g. pytest, jest, go test>",
  "single_test_command": "<command from repo-map.md, or the greenfield choice, with a placeholder for the test path/name>",
  "tests": [
    {
      "ac_id": "AC-1",
      "file": "tests/<feature-slug>/test_something.py",
      "test_name": "test_login_rejects_empty_password",
      "status": "red",
      "found_in_round": 0
    },
    {
      "ac_id": "AC-2",
      "file": "tests/<feature-slug>/test_something.py",
      "test_name": "test_existing_sessions_unaffected",
      "status": "green",
      "found_in_round": 0
    }
  ]
}
```

## Field rules

**`framework`** and **`single_test_command`** — copied from `repo-map.md` verbatim (or the
greenfield choice recorded in `design.md`). The orchestrator uses `single_test_command` to
re-run one test at a time during the dev↔QA loop without re-running the whole suite.

**`tests[].ac_id`** — must be a real `AC-n` from `requirements.md`. Exactly one entry per
acceptance criterion row — no `AC-n` should appear twice, and no `AC-n` should be missing.

**`tests[].status`** — `"red"` for a test written against a not-yet-implemented feature,
`"green"` for a regression test whose behaviour is already correct today. The orchestrator uses
this to know which tests are the dev agent's actual exit condition (`red` → must flip to
passing) versus which exist purely to catch a future regression.

**`tests[].found_in_round`** — `0` for the initial suite. When QA files a bug against dev output
mid-loop, the new test entry gets the round number it was found in, so the orchestrator's "same
test fails twice with the same error, stop" guardrail can distinguish a new finding from a repeat
failure of an existing one.

## Orchestrator contract

The orchestrator is responsible for:

- Running `single_test_command` against each `red` test after a dev agent reports a task done,
  and treating the task as incomplete until every `red` test tied to that task's `covers` list
  passes.
- Re-running `green` tests too, on every round, to catch regressions the dev agent introduced
  elsewhere.
- Tracking failure signatures per test across rounds: if the same test fails with the same error
  twice in a row, stop and escalate to a human rather than sending it back for a third attempt.
- Enforcing the max-rounds limit (recommended default: 3 dev↔QA rounds per task) independent of
  whether the failure signature is changing.

## Naming

- Feature slug matches `requirements.md` and `design.md`.
- `ac_id` values are never renumbered — they mirror `requirements.md`'s `AC-n` IDs exactly.
