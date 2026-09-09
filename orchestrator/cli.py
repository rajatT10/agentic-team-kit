"""`python -m orchestrator` — check a plan, or print the waves it schedules into.

Both subcommands exit non-zero on an unsafe plan so this can sit in CI as the gate
between `dev-task-split` and any agent actually writing code.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .model import PlanError
from .parse import load_plan
from .schedule import build_schedule
from .validate import validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description=(
            "Validate and schedule a task plan (tasks.json, or a Spec Kit tasks.md)."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    check = subcommands.add_parser(
        "validate", help="check the plan for cycles and unguarded file collisions"
    )
    check.add_argument("plan", help="path to tasks.json or tasks.md")
    check.add_argument("--json", action="store_true", help="machine-readable output")

    schedule = subcommands.add_parser(
        "schedule", help="print the execution waves the plan resolves to"
    )
    schedule.add_argument("plan", help="path to tasks.json or tasks.md")
    schedule.add_argument("--json", action="store_true", help="machine-readable output")
    schedule.add_argument(
        "--worktree-root",
        default=".worktrees",
        help="directory the per-task worktrees are created under (default: .worktrees)",
    )

    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
        if args.command == "validate":
            return _run_validate(plan, as_json=args.json)
        return _run_schedule(plan, args.worktree_root, as_json=args.json)
    except PlanError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


def _run_validate(plan, *, as_json: bool) -> int:
    report = validate(plan)
    if as_json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "feature": plan.feature,
                    "tasks": len(plan.tasks),
                    "collisions": [asdict(item) for item in report.collisions],
                    "cycles": [list(cycle) for cycle in report.cycles],
                    "unowned": list(report.unowned),
                },
                indent=2,
            )
        )
    else:
        print(f"{plan.feature}: {len(plan.tasks)} tasks from {plan.source}")
        print(report.describe())
    return 0 if report.ok else 1


def _run_schedule(plan, worktree_root: str, *, as_json: bool) -> int:
    schedule = build_schedule(plan, worktree_root=worktree_root)
    if as_json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "feature": schedule.feature,
                    "mode": schedule.mode,
                    "max_concurrency": schedule.max_concurrency,
                    "waves": [
                        {
                            "index": wave.index,
                            "assignments": [
                                asdict(assignment) for assignment in wave.assignments
                            ],
                        }
                        for wave in schedule.waves
                    ],
                },
                indent=2,
            )
        )
        return 0

    print(
        f"{schedule.feature}: {schedule.task_count} tasks in {len(schedule.waves)} "
        f"wave(s), max concurrency {schedule.max_concurrency} (mode: {schedule.mode})"
    )
    for wave in schedule.waves:
        label = "parallel" if wave.parallel else "single"
        print(f"\n  wave {wave.index} ({label}):")
        for assignment in wave.assignments:
            review = " [needs human review]" if assignment.requires_human_review else ""
            print(f"    {assignment.task_id}  {assignment.title}{review}")
            print(f"      owns:     {', '.join(assignment.owns)}")
            print(f"      worktree: {assignment.worktree}  branch: {assignment.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
