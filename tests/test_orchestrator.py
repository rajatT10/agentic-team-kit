"""Tests for the scheduling core.

Written against stdlib `unittest` on purpose: the kit is meant to drop into any repo, and
a safety check that needs its own dependency install is a safety check people skip.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import (  # noqa: E402
    Plan,
    PlanError,
    Task,
    build_schedule,
    globs_intersect,
    load_plan,
    validate,
)


class GlobIntersectionTests(unittest.TestCase):
    """The `owns` collision test. Everything else trusts these answers."""

    def assert_intersects(self, left: str, right: str) -> None:
        self.assertTrue(
            globs_intersect(left, right), f"expected {left!r} to intersect {right!r}"
        )
        # Intersection is a symmetric relation; a directional bug here would make
        # collision detection depend on task ordering.
        self.assertTrue(globs_intersect(right, left), "intersection is not symmetric")

    def assert_disjoint(self, left: str, right: str) -> None:
        self.assertFalse(
            globs_intersect(left, right), f"expected {left!r} to be disjoint {right!r}"
        )
        self.assertFalse(globs_intersect(right, left), "disjointness is not symmetric")

    def test_globstar_covers_files_beneath_it(self):
        self.assert_intersects("src/api/**", "src/api/users.ts")

    def test_sibling_directories_are_disjoint(self):
        self.assert_disjoint("src/api/**", "src/ui/**")

    def test_single_star_does_not_cross_a_slash(self):
        self.assert_disjoint("src/*.ts", "src/api/users.ts")
        self.assert_intersects("src/*.ts", "src/index.ts")

    def test_star_in_the_middle_matches_one_segment(self):
        self.assert_intersects("src/*/model.ts", "src/api/model.ts")
        self.assert_disjoint("src/*/model.ts", "src/a/b/model.ts")

    def test_globstar_dir_matches_zero_segments(self):
        # `src/**/test.ts` must cover `src/test.ts`, not just nested copies. Getting this
        # wrong would let two tasks write the same top-level file concurrently.
        self.assert_intersects("src/**/test.ts", "src/test.ts")
        self.assert_intersects("src/**/test.ts", "src/a/b/test.ts")

    def test_distinct_literals_never_collide(self):
        self.assert_disjoint("src/a.ts", "src/b.ts")

    def test_bare_globstar_owns_everything(self):
        self.assert_intersects("**", "anything/at/all.ts")
        self.assert_intersects("**", "src/api/**")

    def test_question_mark_is_exactly_one_character(self):
        self.assert_intersects("src/?.ts", "src/a.ts")
        self.assert_disjoint("src/?.ts", "src/ab.ts")

    def test_different_extensions_are_disjoint(self):
        self.assert_disjoint("src/api/*.ts", "src/api/*.js")

    def test_two_wildcard_patterns_can_still_collide(self):
        # Neither pattern is a prefix of the other, but `src/api/users.ts` matches both.
        self.assert_intersects("src/api/*.ts", "src/*/users.ts")

    def test_trailing_slash_means_the_whole_directory(self):
        self.assert_intersects("src/api/", "src/api/users.ts")

    def test_leading_dot_slash_is_ignored(self):
        self.assert_intersects("./src/api/**", "src/api/x.ts")


def _plan(*tasks: Task, mode: str = "parallel") -> Plan:
    return Plan(feature="demo", tasks=tasks, mode=mode)


class ValidationTests(unittest.TestCase):
    def test_disjoint_tasks_pass(self):
        report = validate(
            _plan(
                Task(id="T1", title="api", owns=("src/api/**",)),
                Task(id="T2", title="ui", owns=("src/ui/**",)),
            )
        )
        self.assertTrue(report.ok)

    def test_overlapping_tasks_without_an_edge_are_rejected(self):
        report = validate(
            _plan(
                Task(id="T1", title="api", owns=("src/api/**",)),
                Task(id="T2", title="also api", owns=("src/api/users.ts",)),
            )
        )
        self.assertFalse(report.ok)
        self.assertEqual(len(report.collisions), 1)
        self.assertIn("T1", report.describe())
        self.assertIn("T2", report.describe())

    def test_overlap_is_allowed_when_ordered_by_a_dependency(self):
        report = validate(
            _plan(
                Task(id="T1", title="api", owns=("src/api/**",)),
                Task(
                    id="T2",
                    title="also api",
                    owns=("src/api/users.ts",),
                    depends_on=("T1",),
                ),
            )
        )
        self.assertTrue(report.ok, report.describe())

    def test_overlap_is_allowed_across_a_transitive_dependency(self):
        report = validate(
            _plan(
                Task(id="T1", title="api", owns=("src/api/**",)),
                Task(id="T2", title="ui", owns=("src/ui/**",), depends_on=("T1",)),
                Task(
                    id="T3",
                    title="api again",
                    owns=("src/api/users.ts",),
                    depends_on=("T2",),
                ),
            )
        )
        self.assertTrue(report.ok, report.describe())

    def test_cycles_are_reported(self):
        report = validate(
            _plan(
                Task(id="T1", title="a", owns=("a/**",), depends_on=("T2",)),
                Task(id="T2", title="b", owns=("b/**",), depends_on=("T1",)),
            )
        )
        self.assertFalse(report.ok)
        self.assertTrue(report.cycles)

    def test_task_owning_nothing_is_rejected_at_construction(self):
        with self.assertRaises(PlanError):
            Task(id="T1", title="vague", owns=())

    def test_unknown_dependency_is_rejected(self):
        with self.assertRaises(PlanError):
            _plan(Task(id="T1", title="a", owns=("a/**",), depends_on=("T9",)))


class ScheduleTests(unittest.TestCase):
    def test_independent_tasks_share_a_wave(self):
        schedule = build_schedule(
            _plan(
                Task(id="T1", title="api", owns=("src/api/**",)),
                Task(id="T2", title="ui", owns=("src/ui/**",)),
            )
        )
        self.assertEqual(len(schedule.waves), 1)
        self.assertEqual(schedule.max_concurrency, 2)

    def test_dependency_forces_a_second_wave(self):
        schedule = build_schedule(
            _plan(
                Task(id="T1", title="api", owns=("src/api/**",)),
                Task(id="T2", title="ui", owns=("src/ui/**",), depends_on=("T1",)),
            )
        )
        self.assertEqual([len(w.assignments) for w in schedule.waves], [1, 1])

    def test_sequential_mode_never_batches(self):
        schedule = build_schedule(
            _plan(
                Task(id="T1", title="api", owns=("src/api/**",)),
                Task(id="T2", title="ui", owns=("src/ui/**",)),
                mode="sequential",
            )
        )
        self.assertEqual(schedule.max_concurrency, 1)
        self.assertEqual(len(schedule.waves), 2)

    def test_unsafe_plan_is_refused_rather_than_scheduled(self):
        with self.assertRaises(PlanError):
            build_schedule(
                _plan(
                    Task(id="T1", title="api", owns=("src/api/**",)),
                    Task(id="T2", title="api too", owns=("src/api/users.ts",)),
                )
            )

    def test_each_assignment_gets_its_own_worktree_and_branch(self):
        schedule = build_schedule(
            _plan(
                Task(id="T1", title="api", owns=("src/api/**",)),
                Task(id="T2", title="ui", owns=("src/ui/**",)),
            )
        )
        assignments = schedule.waves[0].assignments
        paths = {a.worktree for a in assignments}
        branches = {a.branch for a in assignments}
        self.assertEqual(len(paths), 2)
        self.assertEqual(len(branches), 2)


class ParsingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_tasks_json_round_trips(self):
        path = self.root / "tasks.json"
        path.write_text(
            json.dumps(
                {
                    "feature": "dark-mode",
                    "mode": "parallel",
                    "tasks": [
                        {
                            "id": "T1",
                            "title": "theme tokens",
                            "covers": ["AC-1"],
                            "owns": ["src/theme/**"],
                            "depends_on": [],
                        },
                        {
                            "id": "T2",
                            "title": "toggle",
                            "covers": ["AC-2"],
                            "owns": ["src/components/Toggle.tsx"],
                            "depends_on": ["T1"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        plan = load_plan(path)
        self.assertEqual(plan.feature, "dark-mode")
        self.assertEqual(plan.by_id["T2"].depends_on, ("T1",))
        self.assertTrue(validate(plan).ok)

    def test_speckit_markdown_import_recovers_file_ownership(self):
        path = self.root / "tasks.md"
        path.write_text(
            "\n".join(
                [
                    "# Tasks",
                    "- [ ] T001 Create project structure per implementation plan",
                    "- [ ] T005 [P] Implement auth middleware in src/middleware/auth.py",
                    "- [ ] T012 [P] [US1] Create User model in src/models/user.py",
                ]
            ),
            encoding="utf-8",
        )
        plan = load_plan(path)
        self.assertEqual([t.id for t in plan.tasks], ["T001", "T005", "T012"])
        self.assertEqual(plan.by_id["T005"].owns, ("src/middleware/auth.py",))
        self.assertEqual(plan.by_id["T012"].covers, ("US1",))

    def test_speckit_task_naming_no_file_is_isolated_not_assumed_safe(self):
        # T001 names no path. Treating that as "owns nothing, safe to parallelise" is the
        # dangerous reading, so it must come back owning everything instead.
        path = self.root / "tasks.md"
        path.write_text(
            "- [ ] T001 Create project structure per implementation plan\n"
            "- [ ] T002 [P] Add model in src/models/user.py\n",
            encoding="utf-8",
        )
        plan = load_plan(path)
        self.assertEqual(plan.by_id["T001"].owns, ("**",))
        report = validate(plan)
        self.assertIn("T001", report.unowned)

    def test_speckit_non_parallel_tasks_act_as_phase_barriers(self):
        # Spec Kit's ordering is phase-based, not line-based: `[P]` tasks in one run are
        # siblings under the barrier before them, and the next non-`[P]` task waits for
        # all of them. Reading it as "each task depends on the previous line" would
        # serialise work that is genuinely parallel.
        path = self.root / "tasks.md"
        path.write_text(
            "\n".join(
                [
                    "- [ ] T001 Create project structure per implementation plan",
                    "- [ ] T005 [P] Auth middleware in src/middleware/auth.py",
                    "- [ ] T012 [P] [US1] User model in src/models/user.py",
                    "- [ ] T014 [US1] UserService in src/services/user_service.py",
                ]
            ),
            encoding="utf-8",
        )
        plan = load_plan(path)
        self.assertEqual(plan.by_id["T005"].depends_on, ("T001",))
        self.assertEqual(plan.by_id["T012"].depends_on, ("T001",))
        self.assertEqual(plan.by_id["T014"].depends_on, ("T005", "T012"))

        schedule = build_schedule(plan)
        self.assertEqual([len(w.assignments) for w in schedule.waves], [1, 2, 1])

    def test_unsupported_extension_is_rejected(self):
        path = self.root / "tasks.yaml"
        path.write_text("tasks: []", encoding="utf-8")
        with self.assertRaises(PlanError):
            load_plan(path)


if __name__ == "__main__":
    unittest.main()
