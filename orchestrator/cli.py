"""`python -m orchestrator` — check a plan, or print the waves it schedules into.

Both subcommands exit non-zero on an unsafe plan so this can sit in CI as the gate
between `dev-task-split` and any agent actually writing code.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .config import ConfigError, load_config, write_template
from .model import PlanError
from .parse import load_plan
from .review import build_description, collect_diff
from .runner import Status, run_feature
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

    execute = subcommands.add_parser(
        "run", help="dispatch dev agents wave by wave and verify each task"
    )
    execute.add_argument("plan", help="path to tasks.json or tasks.md")
    execute.add_argument("--json", action="store_true", help="machine-readable output")
    execute.add_argument("--config", default=None, help="path to config.json")
    execute.add_argument("--repo", default=".", help="repository root (default: .)")
    execute.add_argument(
        "--describe",
        default=None,
        metavar="PATH",
        help="write a pull request description for the run to PATH ('-' for stdout)",
    )

    init = subcommands.add_parser(
        "init", help="write a starter .agentteam/config.json"
    )
    init.add_argument(
        "--path", default=None, help="where to write it (default: .agentteam/config.json)"
    )

    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            written = write_template(args.path) if args.path else write_template()
            print(f"wrote {written}")
            return 0

        plan = load_plan(args.plan)
        if args.command == "validate":
            return _run_validate(plan, as_json=args.json)
        if args.command == "schedule":
            return _run_schedule(plan, args.worktree_root, as_json=args.json)
        return _run_execute(plan, args, as_json=args.json)
    except (PlanError, ConfigError) as exc:
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


def _run_execute(plan, args, *, as_json: bool) -> int:
    config = load_config(args.config)

    def report(event: str, **payload) -> None:
        if as_json:
            return
        if event == "wave-start":
            wave = payload["wave"]
            names = ", ".join(a.task_id for a in wave.assignments)
            print(f"\nwave {wave.index}: {names}", flush=True)
        elif event == "round-end":
            mark = "pass" if payload["passed"] else "fail"
            print(
                f"  {payload['task_id']} round {payload['round']}: {mark}", flush=True
            )
        elif event == "merge-conflict":
            print(f"  {payload['outcome'].task_id}: merge conflict", flush=True)

    if not as_json:
        if config.manifest_path:
            verify = f"per acceptance criterion, from {config.manifest_path}"
        else:
            verify = config.verify_display() or "(none configured)"
        print(
            f"agent:  {' '.join(config.agent.command)}\n"
            f"verify: {verify}\n"
            f"config: {config.source}"
        )

    result = run_feature(plan, config, repo=args.repo, on_event=report)

    if as_json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "feature": result.feature,
                    "integration_branch": result.integration_branch,
                    "tasks": [
                        {
                            "task_id": outcome.task_id,
                            "status": outcome.status.value,
                            "rounds": outcome.rounds,
                            "branch": outcome.branch,
                            "head": outcome.head,
                            "detail": outcome.detail,
                        }
                        for outcome in result.outcomes
                    ],
                },
                indent=2,
            )
        )
    else:
        print("\n" + result.summary())
        held = [o for o in result.outcomes if o.status is Status.HELD]
        if held:
            print(
                "\nheld for human review before merge: "
                + ", ".join(o.task_id for o in held)
            )

    if args.describe:
        _write_description(plan, result, args, config)

    return 0 if result.ok else 1


def _write_description(plan, result, args, config) -> None:
    try:
        diff = collect_diff(args.repo, config.base_ref, config.integration_branch)
    except Exception:  # noqa: BLE001 - a missing branch must not lose the run's summary
        diff = None

    body = build_description(plan, result, diff)
    if args.describe == "-":
        print("\n" + body)
        return
    path = Path(args.describe)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    if not args.json:
        print(f"\nwrote pull request description to {path}")


if __name__ == "__main__":
    raise SystemExit(main())
