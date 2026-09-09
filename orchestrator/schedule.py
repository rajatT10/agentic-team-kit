"""Turn a validated plan into execution waves.

A wave is a set of tasks that may run at the same time, each in its own git worktree. The
grouping is derived, not declared: tasks land in the same wave only when the DAG puts no
edge between them, and `validate` has already established that no-edge implies no shared
files. The `mode` field in `tasks.json` is documentation of intent — it can narrow the
schedule to one task per wave, but it can never widen it past what the globs allow.
"""

from __future__ import annotations

from dataclasses import dataclass

from .globset import overlapping_pairs
from .model import Plan, PlanError
from .validate import validate


@dataclass(frozen=True)
class Assignment:
    task_id: str
    title: str
    owns: tuple[str, ...]
    worktree: str
    branch: str
    requires_human_review: bool


@dataclass(frozen=True)
class Wave:
    index: int
    assignments: tuple[Assignment, ...]

    @property
    def parallel(self) -> bool:
        return len(self.assignments) > 1


@dataclass(frozen=True)
class Schedule:
    feature: str
    waves: tuple[Wave, ...]
    mode: str

    @property
    def task_count(self) -> int:
        return sum(len(wave.assignments) for wave in self.waves)

    @property
    def max_concurrency(self) -> int:
        return max((len(wave.assignments) for wave in self.waves), default=0)


def build_schedule(plan: Plan, worktree_root: str = ".worktrees") -> Schedule:
    """Group `plan` into waves. Raises `PlanError` if the plan is unsafe."""
    report = validate(plan)
    if not report.ok:
        raise PlanError(
            "refusing to schedule an unsafe plan:\n" + report.describe()
        )

    levels = _depths(plan)
    grouped: dict[int, list[str]] = {}
    for task_id, depth in levels.items():
        grouped.setdefault(depth, []).append(task_id)

    waves: list[Wave] = []
    for index in sorted(grouped):
        members = sorted(grouped[index], key=_task_sort_key)
        if plan.mode == "sequential":
            # Intent is one-at-a-time; keep the dependency order but never batch.
            for member in members:
                waves.append(
                    Wave(
                        index=len(waves),
                        assignments=(_assign(plan, member, worktree_root),),
                    )
                )
            continue

        _assert_disjoint(plan, members)
        waves.append(
            Wave(
                index=len(waves),
                assignments=tuple(
                    _assign(plan, member, worktree_root) for member in members
                ),
            )
        )

    return Schedule(feature=plan.feature, waves=tuple(waves), mode=plan.mode)


def _assign(plan: Plan, task_id: str, worktree_root: str) -> Assignment:
    task = plan.by_id[task_id]
    slug = f"{plan.feature}-{task.id}".lower().replace("_", "-")
    return Assignment(
        task_id=task.id,
        title=task.title,
        owns=task.owns,
        worktree=f"{worktree_root}/{slug}",
        branch=f"agent/{slug}",
        requires_human_review=task.requires_human_review,
    )


def _assert_disjoint(plan: Plan, members: list[str]) -> None:
    """Belt-and-braces: re-prove disjointness on the exact set about to run together.

    `validate` already guarantees this for a well-formed DAG. Re-checking here means a
    future change to the depth calculation cannot quietly put two colliding tasks in one
    wave — the failure surfaces as a refusal to schedule rather than as a merge conflict.
    """
    for index, left_id in enumerate(members):
        for right_id in members[index + 1 :]:
            overlaps = overlapping_pairs(
                list(plan.by_id[left_id].owns), list(plan.by_id[right_id].owns)
            )
            if overlaps:
                raise PlanError(
                    f"internal error: {left_id} and {right_id} were grouped into one "
                    f"wave but their globs overlap ({overlaps})"
                )


def _depths(plan: Plan) -> dict[str, int]:
    depth: dict[str, int] = {}

    def resolve(task_id: str) -> int:
        if task_id in depth:
            return depth[task_id]
        dependencies = plan.by_id[task_id].depends_on
        depth[task_id] = (
            0 if not dependencies else 1 + max(resolve(dep) for dep in dependencies)
        )
        return depth[task_id]

    for task in plan.tasks:
        resolve(task.id)
    return depth


def _task_sort_key(task_id: str) -> tuple[int, str]:
    digits = "".join(char for char in task_id if char.isdigit())
    return (int(digits) if digits else 0, task_id)
