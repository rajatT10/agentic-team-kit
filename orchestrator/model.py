"""The task plan as the orchestrator sees it.

`tasks.json` is the contract described in
`.claude/skills/dev-task-split/references/tasks-schema.md`. This module is the only place
that knows its shape, so a schema change lands here rather than across the executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class PlanError(ValueError):
    """The plan is malformed or unsafe to execute. Never raised for a merely slow plan."""


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    owns: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    covers: tuple[str, ...] = ()
    requires_human_review: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise PlanError("task is missing an id")
        if not self.owns:
            raise PlanError(
                f"{self.id} declares no `owns` globs; a task that owns nothing cannot be "
                "scheduled safely because the orchestrator has no way to prove it does "
                "not collide with anything else"
            )


@dataclass(frozen=True)
class Plan:
    feature: str
    tasks: tuple[Task, ...]
    mode: str = "sequential"
    requirements: str = ""
    design: str = ""
    source: str = ""

    by_id: dict[str, Task] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        seen: dict[str, Task] = {}
        for task in self.tasks:
            if task.id in seen:
                raise PlanError(f"duplicate task id {task.id!r}")
            seen[task.id] = task
        # `by_id` is a cache, not input; frozen dataclasses need the back door.
        object.__setattr__(self, "by_id", seen)

        for task in self.tasks:
            for dependency in task.depends_on:
                if dependency not in seen:
                    raise PlanError(
                        f"{task.id} depends on {dependency!r}, which is not in the plan"
                    )
                if dependency == task.id:
                    raise PlanError(f"{task.id} depends on itself")

        if self.mode not in {"sequential", "parallel"}:
            raise PlanError(
                f"mode must be 'sequential' or 'parallel', got {self.mode!r}"
            )
