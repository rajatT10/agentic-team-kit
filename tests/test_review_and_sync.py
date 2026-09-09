"""Tests for the PR description generator and the per-tool shim sync.

Both are deterministic on purpose. The description is the artifact a human reads before
approving agent-written code, and the shims are what every tool loads — neither is a good
place for a paraphrasing step that can quietly be wrong.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from orchestrator import Plan, Status, Task, build_description  # noqa: E402
from orchestrator.review import DiffStat, collect_diff  # noqa: E402
from orchestrator.runner import RunResult, TaskOutcome, WaveOutcome  # noqa: E402
from orchestrator.worktree import git  # noqa: E402

import sync_agent_files  # noqa: E402


def _plan() -> Plan:
    return Plan(
        feature="dark-mode",
        requirements="docs/features/dark-mode/requirements.md",
        tasks=(
            Task(id="T1", title="Theme tokens", owns=("src/theme/**",), covers=("AC-1",)),
            Task(id="T2", title="Toggle", owns=("src/ui/**",), covers=("AC-2",)),
        ),
    )


def _result(*outcomes: TaskOutcome) -> RunResult:
    return RunResult(
        feature="dark-mode",
        integration_branch="agent/integration",
        waves=[WaveOutcome(index=0, outcomes=list(outcomes))],
    )


class DescriptionTests(unittest.TestCase):
    def test_lists_every_task_with_its_globs(self):
        body = build_description(
            _plan(),
            _result(
                TaskOutcome(task_id="T1", status=Status.COMPLETED, rounds=1),
                TaskOutcome(task_id="T2", status=Status.COMPLETED, rounds=2),
            ),
        )
        self.assertIn("T1 — Theme tokens", body)
        self.assertIn("`src/theme/**`", body)
        self.assertIn("`src/ui/**`", body)
        self.assertIn("docs/features/dark-mode/requirements.md", body)

    def test_partial_run_is_reported_not_hidden(self):
        # A description that only lists successes is worse than no description: the
        # reviewer approves believing the feature is complete.
        body = build_description(
            _plan(),
            _result(
                TaskOutcome(task_id="T1", status=Status.COMPLETED, rounds=1),
                TaskOutcome(
                    task_id="T2",
                    status=Status.FAILED,
                    rounds=3,
                    detail="AC-2 FAILED (tests/t.py::test_toggle)",
                ),
            ),
        )
        self.assertIn("1/2 task(s) complete", body)
        self.assertIn("Not ready to merge", body)
        self.assertIn("T2 (Toggle)", body)

    def test_held_task_is_flagged_even_though_it_passed(self):
        body = build_description(
            _plan(),
            _result(
                TaskOutcome(task_id="T1", status=Status.COMPLETED),
                TaskOutcome(task_id="T2", status=Status.HELD, detail="held for review"),
            ),
        )
        self.assertIn("held for human review", body)
        # Held counts as ok for the run, but must still appear as a merge blocker.
        self.assertIn("Not ready to merge", body)

    def test_criteria_table_merges_across_tasks(self):
        body = build_description(
            _plan(),
            _result(
                TaskOutcome(
                    task_id="T1", status=Status.COMPLETED, criteria={"AC-1": True}
                ),
                TaskOutcome(
                    task_id="T2", status=Status.FAILED, criteria={"AC-1": False, "AC-2": False}
                ),
            ),
        )
        self.assertIn("Acceptance criteria", body)
        # AC-1 is green for T1 and red for T2, so overall it is not green.
        ac1_row = [line for line in body.splitlines() if line.startswith("| AC-1 ")][0]
        self.assertIn("**fail**", ac1_row)

    def test_diff_summary_is_included_when_available(self):
        body = build_description(
            _plan(),
            _result(TaskOutcome(task_id="T1", status=Status.COMPLETED)),
            DiffStat(files=2, insertions=40, deletions=3, paths=("a.ts", "b.ts")),
        )
        self.assertIn("2 file(s), +40 / −3", body)
        self.assertIn("`a.ts`", body)


class DiffCollectionTests(unittest.TestCase):
    def test_collect_diff_counts_real_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git("init", "-q", "-b", "main", cwd=repo)
            git("config", "user.email", "t@e.com", cwd=repo)
            git("config", "user.name", "T", cwd=repo)
            (repo / "seed.txt").write_text("one\n", encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "seed", cwd=repo)

            git("checkout", "-q", "-b", "work", cwd=repo)
            (repo / "added.txt").write_text("a\nb\n", encoding="utf-8")
            git("add", "-A", cwd=repo)
            git("commit", "-q", "-m", "work", cwd=repo)

            diff = collect_diff(repo, "main", "work")
            self.assertEqual(diff.files, 1)
            self.assertEqual(diff.insertions, 2)
            self.assertIn("added.txt", diff.paths)


class SyncTests(unittest.TestCase):
    def test_generated_files_are_current(self):
        # The check the CI job runs. A failure here means someone edited a SKILL.md and
        # did not regenerate, so Cursor and Claude Code would disagree.
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = sync_agent_files.main(["--root", str(ROOT), "--check"])
        self.assertEqual(exit_code, 0, "run: python3 tools/sync_agent_files.py")

    def test_every_skill_becomes_a_cursor_command(self):
        skills = sync_agent_files.discover(ROOT)
        self.assertTrue(skills)
        for skill in skills:
            command = ROOT / ".cursor" / "commands" / f"{skill.name}.md"
            self.assertTrue(command.exists(), f"missing {command}")
            self.assertIn(f"/{skill.name}", command.read_text(encoding="utf-8"))

    def test_agents_md_names_every_skill(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for skill in sync_agent_files.discover(ROOT):
            self.assertIn(skill.name, text)

    def test_check_mode_detects_a_stale_file(self):
        outputs = sync_agent_files.plan_outputs(ROOT)
        target = ROOT / "AGENTS.md"
        original = target.read_text(encoding="utf-8")
        try:
            target.write_text(original + "\nhand edit\n", encoding="utf-8")
            # The tool reports the stale file on stderr; that is the behaviour under
            # test, not output this run should print.
            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = sync_agent_files.main(["--root", str(ROOT), "--check"])
            self.assertEqual(
                exit_code, 1, "a hand-edited generated file must fail --check"
            )
        finally:
            target.write_text(outputs[target], encoding="utf-8")

    def test_frontmatter_description_survives_into_the_shim(self):
        skills = {skill.name: skill for skill in sync_agent_files.discover(ROOT)}
        skill = skills["pm-requirements"]
        self.assertIn("acceptance criteria", skill.description)
        body = (ROOT / ".cursor" / "commands" / "pm-requirements.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("acceptance criteria", body)
        # The schema reference is a separate file; the shim must point at it or the
        # command loses the contract it is supposed to produce.
        self.assertIn("references/artifact-schema.md", body)


if __name__ == "__main__":
    unittest.main()
