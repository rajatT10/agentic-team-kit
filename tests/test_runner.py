"""End-to-end tests for the dev-agent runner.

The "agent" here is a shell script. That is the point of the design: the runner never
imports a vendor SDK, it renders a command template and runs it, so the whole loop —
worktrees, rounds, verification, merge — is testable without an API key, a network, or a
model that might behave differently on Tuesday.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import (  # noqa: E402
    AgentSpec,
    Plan,
    RunConfig,
    Status,
    Task,
    run_feature,
)
from orchestrator.worktree import git  # noqa: E402


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


class RunnerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()

        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.email", "test@example.com", cwd=self.repo)
        git("config", "user.name", "Test", cwd=self.repo)
        (self.repo / "README.md").write_text("seed\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "seed", cwd=self.repo)

    def config(self, agent_body: str, verify_body: str, **overrides) -> RunConfig:
        agent = _script(self.root / "agent.sh", agent_body)
        verify = _script(self.root / "verify.sh", verify_body)
        defaults = dict(
            agent=AgentSpec(command=("/bin/sh", str(agent), "{prompt}"), timeout_seconds=60),
            verify_command=("/bin/sh", str(verify)),
            verify_timeout_seconds=60,
            max_rounds=3,
            worktree_root=str(self.root / "worktrees"),
        )
        defaults.update(overrides)
        return RunConfig(**defaults)

    def plan(self, *tasks: Task, mode: str = "parallel") -> Plan:
        return Plan(feature="demo", tasks=tasks, mode=mode)

    def files_on(self, branch: str) -> set[str]:
        listing = git("ls-tree", "-r", "--name-only", branch, cwd=self.repo).stdout
        return set(listing.split())


class HappyPathTests(RunnerTestCase):
    def test_parallel_tasks_are_verified_and_merged(self):
        # Each agent writes the file its task owns; verification passes once both the
        # agent's own file exists and the tree still builds.
        config = self.config(
            agent_body='case "$1" in\n'
            '  *T1*) mkdir -p src/api && echo api > src/api/users.ts ;;\n'
            '  *T2*) mkdir -p src/ui && echo ui > src/ui/Toggle.tsx ;;\n'
            "esac\n",
            verify_body='test -f src/api/users.ts || test -f src/ui/Toggle.tsx\n',
        )
        result = run_feature(
            self.plan(
                Task(id="T1", title="api", owns=("src/api/**",)),
                Task(id="T2", title="ui", owns=("src/ui/**",)),
            ),
            config,
            repo=self.repo,
        )

        self.assertTrue(result.ok, result.summary())
        self.assertEqual(
            {o.status for o in result.outcomes}, {Status.COMPLETED}, result.summary()
        )
        merged = self.files_on(config.integration_branch)
        self.assertIn("src/api/users.ts", merged)
        self.assertIn("src/ui/Toggle.tsx", merged)

    def test_dependent_wave_sees_the_previous_wave_result(self):
        # T2 depends on T1, so its worktree is cut from the integration branch after T1
        # merged. If waves did not merge in order, T1's file would not be visible here.
        config = self.config(
            agent_body='case "$1" in\n'
            '  *T1*) mkdir -p src/api && echo one > src/api/base.ts ;;\n'
            '  *T2*) test -f src/api/base.ts && mkdir -p src/ui && echo two > src/ui/on.ts ;;\n'
            "esac\n",
            verify_body='test -f src/api/base.ts\n',
        )
        result = run_feature(
            self.plan(
                Task(id="T1", title="base", owns=("src/api/**",)),
                Task(id="T2", title="on top", owns=("src/ui/**",), depends_on=("T1",)),
            ),
            config,
            repo=self.repo,
        )

        self.assertTrue(result.ok, result.summary())
        self.assertIn("src/ui/on.ts", self.files_on(config.integration_branch))


class RetryTests(RunnerTestCase):
    def test_agent_gets_another_round_after_a_failing_verification(self):
        counter = self.state / "rounds"
        config = self.config(
            agent_body=f'C="{counter}"\n'
            'N=$(cat "$C" 2>/dev/null || echo 0); N=$((N+1)); echo "$N" > "$C"\n'
            'mkdir -p src\n'
            'if [ "$N" -ge 2 ]; then echo good > src/thing.ts; else echo bad > src/other.ts; fi\n',
            verify_body="test -f src/thing.ts\n",
        )
        result = run_feature(
            self.plan(Task(id="T1", title="retry", owns=("src/**",))),
            config,
            repo=self.repo,
        )

        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, Status.COMPLETED, outcome.detail)
        self.assertEqual(outcome.rounds, 2)

    def test_identical_failure_twice_escalates_instead_of_retrying(self):
        # The same failure twice means the last round changed nothing that mattered.
        # Spending a third round on it is worse than handing it to a human.
        config = self.config(
            agent_body="mkdir -p src && echo nope > src/wrong.ts\n",
            verify_body='echo "expected src/thing.ts" >&2; exit 1\n',
            max_rounds=5,
        )
        result = run_feature(
            self.plan(Task(id="T1", title="never passes", owns=("src/**",))),
            config,
            repo=self.repo,
        )

        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, Status.ESCALATED)
        self.assertEqual(outcome.rounds, 2, "should not have reached round 3")
        # The failure text must survive to the caller — that is what a human debugs from.
        self.assertIn("expected src/thing.ts", outcome.detail)

    def test_rounds_are_bounded_when_the_failure_keeps_changing(self):
        # A different failure each round is progress of a sort, so the guardrail stays
        # out of the way and only max_rounds stops it.
        counter = self.state / "verify-rounds"
        config = self.config(
            agent_body="mkdir -p src && echo nope > src/wrong.ts\n",
            verify_body=f'C="{counter}"\n'
            'N=$(cat "$C" 2>/dev/null || echo 0); N=$((N+1)); echo "$N" > "$C"\n'
            'echo "distinct failure number $N" >&2; exit 1\n',
            max_rounds=2,
        )
        result = run_feature(
            self.plan(Task(id="T1", title="never passes", owns=("src/**",))),
            config,
            repo=self.repo,
        )

        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, Status.FAILED)
        self.assertEqual(outcome.rounds, 2)
        self.assertIn("distinct failure number 2", outcome.detail)

    def test_volatile_output_does_not_look_like_a_new_failure(self):
        # Timings and temp paths change every run. If they counted toward the signature,
        # the escalation guardrail would never fire on a real test runner.
        config = self.config(
            agent_body="mkdir -p src && echo nope > src/wrong.ts\n",
            verify_body='echo "failed in 0.$$s at /tmp/run-$$ — same cause" >&2; exit 1\n',
            max_rounds=5,
        )
        result = run_feature(
            self.plan(Task(id="T1", title="t", owns=("src/**",))),
            config,
            repo=self.repo,
        )

        self.assertEqual(result.outcomes[0].status, Status.ESCALATED)
        self.assertEqual(result.outcomes[0].rounds, 2)

    def test_the_agent_is_told_what_failed_last_round(self):
        # The retry prompt has to carry the verification output, otherwise round two is
        # just round one repeated.
        seen = self.state / "prompt"
        config = self.config(
            agent_body=f'printf "%s" "$1" >> "{seen}"\nmkdir -p src && echo x > src/a.ts\n',
            verify_body='echo "DISTINCTIVE-FAILURE-TEXT" >&2; exit 1\n',
            max_rounds=2,
        )
        run_feature(
            self.plan(Task(id="T1", title="t", owns=("src/**",))),
            config,
            repo=self.repo,
        )
        self.assertIn("DISTINCTIVE-FAILURE-TEXT", seen.read_text(encoding="utf-8"))


class PolicyTests(RunnerTestCase):
    def test_review_required_task_is_verified_but_not_merged(self):
        config = self.config(
            agent_body="mkdir -p src && echo x > src/danger.ts\n",
            verify_body="test -f src/danger.ts\n",
        )
        result = run_feature(
            self.plan(
                Task(
                    id="T1",
                    title="touches a danger zone",
                    owns=("src/**",),
                    requires_human_review=True,
                )
            ),
            config,
            repo=self.repo,
        )

        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, Status.HELD)
        self.assertNotIn("src/danger.ts", self.files_on(config.integration_branch))
        # The work is not lost — it is sitting on the task's own branch for review.
        self.assertIn("src/danger.ts", self.files_on(outcome.branch))

    def test_a_failed_wave_stops_the_ones_after_it(self):
        config = self.config(
            agent_body="mkdir -p src\n",
            verify_body="exit 1\n",
            max_rounds=1,
        )
        result = run_feature(
            self.plan(
                Task(id="T1", title="fails", owns=("src/api/**",)),
                Task(id="T2", title="downstream", owns=("src/ui/**",), depends_on=("T1",)),
            ),
            config,
            repo=self.repo,
        )

        statuses = {o.task_id: o.status for o in result.outcomes}
        self.assertEqual(statuses["T1"], Status.FAILED)
        self.assertEqual(statuses["T2"], Status.SKIPPED)

    def test_missing_agent_binary_errors_without_burning_rounds(self):
        # Retrying a command that does not exist just produces the same error three times
        # and hides the real problem behind the last one.
        config = self.config(
            agent_body=":\n", verify_body=":\n", max_rounds=3
        )
        config = RunConfig(
            **{
                **config.__dict__,
                "agent": AgentSpec(command=("definitely-not-a-real-binary", "{prompt}")),
            }
        )
        result = run_feature(
            self.plan(Task(id="T1", title="t", owns=("src/**",))),
            config,
            repo=self.repo,
        )

        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, Status.ERRORED)
        self.assertEqual(outcome.rounds, 1)
        self.assertIn("not found", outcome.detail)

    def test_no_verification_command_is_refused_rather_than_assumed_passing(self):
        config = self.config(agent_body=":\n", verify_body=":\n", max_rounds=1)
        config = RunConfig(**{**config.__dict__, "verify_command": ()})
        result = run_feature(
            self.plan(Task(id="T1", title="t", owns=("src/**",))),
            config,
            repo=self.repo,
        )

        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, Status.FAILED)
        self.assertIn("verify.command", outcome.detail)


class CleanupTests(RunnerTestCase):
    def test_worktrees_are_removed_after_a_wave(self):
        config = self.config(
            agent_body="mkdir -p src && echo x > src/a.ts\n",
            verify_body="test -f src/a.ts\n",
        )
        result = run_feature(
            self.plan(Task(id="T1", title="t", owns=("src/**",))),
            config,
            repo=self.repo,
        )
        self.assertTrue(result.ok, result.summary())
        listed = git("worktree", "list", cwd=self.repo).stdout
        self.assertNotIn("demo-t1", listed)

    def test_worktrees_are_kept_when_asked(self):
        config = self.config(
            agent_body="mkdir -p src && echo x > src/a.ts\n",
            verify_body="test -f src/a.ts\n",
            keep_worktrees=True,
        )
        run_feature(
            self.plan(Task(id="T1", title="t", owns=("src/**",))),
            config,
            repo=self.repo,
        )
        listed = git("worktree", "list", cwd=self.repo).stdout
        self.assertIn("demo-t1", listed)


class PromptTests(RunnerTestCase):
    def test_prompt_names_the_owned_globs_and_the_boundary(self):
        from orchestrator import build_prompt

        prompt = build_prompt(
            Plan(feature="f", tasks=(Task(id="T1", title="t", owns=("src/api/**",)),)),
            Task(id="T1", title="t", owns=("src/api/**",), covers=("AC-1",)),
            verify_command="pytest -q",
        )
        self.assertIn("src/api/**", prompt)
        self.assertIn("AC-1", prompt)
        self.assertIn("pytest -q", prompt)
        # The concurrency boundary is not inferable from the repo, so it must be stated.
        self.assertIn("separate checkouts", prompt)


if __name__ == "__main__":
    unittest.main()
