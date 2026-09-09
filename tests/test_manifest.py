"""Tests for per-acceptance-criterion verification.

The point of the manifest is that "the suite passed" is not the same claim as "AC-3
passed". These tests pin the difference: a task's exit condition is the tests tied to its
own `covers` list, and a criterion nobody wrote a test for fails loudly rather than
sliding through on a green suite.
"""

from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import Plan, RunConfig, Status, Task  # noqa: E402
from orchestrator.agent import AgentSpec  # noqa: E402
from orchestrator.manifest import (  # noqa: E402
    Manifest,
    ManifestError,
    TestEntry,
    cross_check,
    load_manifest,
    run_tests,
)
from orchestrator.runner import run_feature  # noqa: E402
from orchestrator.worktree import git  # noqa: E402

VALID = {
    "feature": "dark-mode",
    "framework": "pytest",
    "single_test_command": "pytest {test}",
    "tests": [
        {"ac_id": "AC-1", "file": "tests/t.py", "test_name": "test_one", "status": "red"},
        {"ac_id": "AC-2", "file": "tests/t.py", "test_name": "test_two", "status": "green"},
    ],
}


class ManifestLoadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, payload: dict) -> Path:
        path = self.root / "test-manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_valid_manifest_loads(self):
        manifest = load_manifest(self.write(VALID))
        self.assertEqual(manifest.feature, "dark-mode")
        self.assertEqual(len(manifest.tests), 2)
        self.assertEqual(manifest.tests[0].selector, "tests/t.py::test_one")

    def test_duplicate_acceptance_criterion_is_rejected(self):
        payload = json.loads(json.dumps(VALID))
        payload["tests"].append(dict(payload["tests"][0]))
        with self.assertRaises(ManifestError) as caught:
            load_manifest(self.write(payload))
        self.assertIn("AC-1", str(caught.exception))

    def test_command_without_a_placeholder_is_rejected(self):
        # Without a placeholder there is no way to run one test on its own, so a failure
        # could never be attributed to a single criterion.
        payload = json.loads(json.dumps(VALID))
        payload["single_test_command"] = "pytest"
        with self.assertRaises(ManifestError):
            load_manifest(self.write(payload))

    def test_unknown_status_is_rejected(self):
        payload = json.loads(json.dumps(VALID))
        payload["tests"][0]["status"] = "amber"
        with self.assertRaises(ManifestError):
            load_manifest(self.write(payload))

    def test_red_and_green_are_separated(self):
        manifest = load_manifest(self.write(VALID))
        self.assertEqual([e.ac_id for e in manifest.for_criteria(("AC-1",))], ["AC-1"])
        self.assertEqual([e.ac_id for e in manifest.regression_tests], ["AC-2"])

    def test_cross_check_reports_both_directions(self):
        manifest = load_manifest(self.write(VALID))
        plan = Plan(
            feature="dark-mode",
            tasks=(
                Task(id="T1", title="t", owns=("src/**",), covers=("AC-1", "AC-9")),
            ),
        )
        notes = "\n".join(cross_check(manifest, plan))
        self.assertIn("AC-9", notes)  # covered by a task, no test
        self.assertIn("AC-2", notes)  # has a test, no task covers it


class SignatureTests(unittest.TestCase):
    def test_same_failure_produces_the_same_signature(self):
        entry = TestEntry(ac_id="AC-1", file="t.py", test_name="x")
        manifest = Manifest(
            feature="f", single_test_command="pytest {test}", tests=(entry,)
        )
        del manifest  # only the result objects matter here
        from orchestrator.manifest import TestResult

        one = TestResult(entry=entry, passed=False, output="boom at 0x7ffd in 1.23s")
        two = TestResult(entry=entry, passed=False, output="boom at 0x1234 in 4.56s")
        self.assertEqual(one.signature, two.signature)

    def test_different_failures_differ(self):
        from orchestrator.manifest import TestResult

        entry = TestEntry(ac_id="AC-1", file="t.py", test_name="x")
        one = TestResult(entry=entry, passed=False, output="assertion failed")
        two = TestResult(entry=entry, passed=False, output="import error")
        self.assertNotEqual(one.signature, two.signature)


class PerCriterionRunnerTests(unittest.TestCase):
    """The manifest wired into a real run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()

        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.email", "t@e.com", cwd=self.repo)
        git("config", "user.name", "T", cwd=self.repo)
        (self.repo / "README.md").write_text("seed\n", encoding="utf-8")
        git("add", "-A", cwd=self.repo)
        git("commit", "-q", "-m", "seed", cwd=self.repo)

        # A stand-in test runner: "AC-n passes" iff the file it maps to exists in the
        # worktree. Enough to prove the wiring without a real framework.
        self.runner = self.root / "fake-pytest.sh"
        self.runner.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            '  *test_theme*) test -f src/theme/tokens.ts ;;\n'
            '  *test_toggle*) test -f src/components/Toggle.tsx ;;\n'
            '  *test_regression*) test -f README.md ;;\n'
            "  *) exit 1 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        self.runner.chmod(self.runner.stat().st_mode | stat.S_IEXEC)

    def manifest_at(self, tests: list[dict]) -> Path:
        path = self.root / "test-manifest.json"
        path.write_text(
            json.dumps(
                {
                    "feature": "dark-mode",
                    "single_test_command": f"/bin/sh {self.runner} {{test}}",
                    "tests": tests,
                }
            ),
            encoding="utf-8",
        )
        return path

    def config(self, manifest_path: Path, agent_body: str, **overrides) -> RunConfig:
        agent = self.root / "agent.sh"
        agent.write_text("#!/bin/sh\n" + agent_body, encoding="utf-8")
        agent.chmod(agent.stat().st_mode | stat.S_IEXEC)
        defaults = dict(
            agent=AgentSpec(command=("/bin/sh", str(agent), "{prompt}"), timeout_seconds=60),
            manifest_path=str(manifest_path),
            verify_timeout_seconds=60,
            max_rounds=2,
            worktree_root=str(self.root / "worktrees"),
        )
        defaults.update(overrides)
        return RunConfig(**defaults)

    def test_task_passes_only_when_its_own_criteria_pass(self):
        manifest = self.manifest_at(
            [
                {"ac_id": "AC-1", "file": "t.py", "test_name": "test_theme", "status": "red"},
                {"ac_id": "AC-2", "file": "t.py", "test_name": "test_toggle", "status": "red"},
            ]
        )
        # The agent only ever satisfies AC-1. T2, which covers AC-2, must not pass on the
        # strength of AC-1 being green.
        config = self.config(
            manifest,
            'mkdir -p src/theme && echo x > src/theme/tokens.ts\n',
            max_rounds=1,
        )
        result = run_feature(
            Plan(
                feature="dark-mode",
                tasks=(
                    Task(id="T1", title="theme", owns=("src/theme/**",), covers=("AC-1",)),
                    Task(
                        id="T2",
                        title="toggle",
                        owns=("src/components/**",),
                        covers=("AC-2",),
                    ),
                ),
                mode="parallel",
            ),
            config,
            repo=self.repo,
        )

        statuses = {o.task_id: o.status for o in result.outcomes}
        self.assertEqual(statuses["T1"], Status.COMPLETED)
        self.assertEqual(statuses["T2"], Status.FAILED)

    def test_outcome_records_which_criteria_passed(self):
        manifest = self.manifest_at(
            [{"ac_id": "AC-1", "file": "t.py", "test_name": "test_theme", "status": "red"}]
        )
        config = self.config(
            manifest, 'mkdir -p src/theme && echo x > src/theme/tokens.ts\n'
        )
        result = run_feature(
            Plan(
                feature="dark-mode",
                tasks=(
                    Task(id="T1", title="theme", owns=("src/theme/**",), covers=("AC-1",)),
                ),
            ),
            config,
            repo=self.repo,
        )
        self.assertEqual(result.outcomes[0].criteria, {"AC-1": True})

    def test_regression_tests_run_alongside_the_task_criteria(self):
        # A green test is not tied to any task's covers list, but it must still run —
        # that is the whole point of marking it green rather than leaving it out.
        manifest = self.manifest_at(
            [
                {"ac_id": "AC-1", "file": "t.py", "test_name": "test_theme", "status": "red"},
                {
                    "ac_id": "AC-9",
                    "file": "t.py",
                    "test_name": "test_regression",
                    "status": "green",
                },
            ]
        )
        config = self.config(
            manifest,
            'mkdir -p src/theme && echo x > src/theme/tokens.ts && rm -f README.md\n',
            max_rounds=1,
        )
        result = run_feature(
            Plan(
                feature="dark-mode",
                tasks=(
                    Task(id="T1", title="theme", owns=("src/**", "README.md"), covers=("AC-1",)),
                ),
            ),
            config,
            repo=self.repo,
        )
        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, Status.FAILED)
        self.assertEqual(outcome.criteria, {"AC-1": True, "AC-9": False})

    def test_task_covering_an_untested_criterion_is_refused(self):
        manifest = self.manifest_at(
            [{"ac_id": "AC-1", "file": "t.py", "test_name": "test_theme", "status": "red"}]
        )
        config = self.config(manifest, ":\n", max_rounds=1)
        result = run_feature(
            Plan(
                feature="dark-mode",
                tasks=(Task(id="T1", title="t", owns=("src/**",), covers=("AC-42",)),),
            ),
            config,
            repo=self.repo,
        )
        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, Status.FAILED)
        self.assertIn("AC-42", outcome.detail)


class DirectRunTests(unittest.TestCase):
    def test_run_tests_attributes_failures_per_criterion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = Manifest(
                feature="f",
                single_test_command="/bin/sh -c 'test -f {file}'",
                tests=(
                    TestEntry(ac_id="AC-1", file="present.txt", test_name=""),
                    TestEntry(ac_id="AC-2", file="absent.txt", test_name=""),
                ),
            )
            (root / "present.txt").write_text("x", encoding="utf-8")
            report = run_tests(manifest, manifest.tests, cwd=root)

            self.assertFalse(report.passed)
            self.assertEqual(report.by_criterion(), {"AC-1": True, "AC-2": False})
            self.assertIn("AC-2", report.describe())


if __name__ == "__main__":
    unittest.main()
