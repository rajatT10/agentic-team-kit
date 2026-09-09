"""The check that makes `owns` a safety mechanism rather than documentation.

The rule from `tasks-schema.md`: any two tasks whose `owns` globs overlap must appear in
each other's dependency chain, directly or transitively. If they don't, two agents can be
scheduled concurrently against the same file — the exact failure that shows up later as a
merge conflict, or worse, as two implementations that both compile and disagree at
runtime.

That is checked here, before any agent runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .globset import overlapping_pairs
from .model import Plan, Task


@dataclass(frozen=True)
class Collision:
    left: str
    right: str
    globs: tuple[tuple[str, str], ...]

    def describe(self) -> str:
        pairs = ", ".join(f"{one!r} ∩ {other!r}" for one, other in self.globs)
        return (
            f"{self.left} and {self.right} both own overlapping paths ({pairs}) but "
            f"neither depends on the other"
        )


@dataclass(frozen=True)
class Report:
    collisions: tuple[Collision, ...] = ()
    cycles: tuple[tuple[str, ...], ...] = ()
    unowned: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.collisions or self.cycles)

    def describe(self) -> str:
        if self.ok and not self.unowned:
            return "plan is safe to execute"
        lines: list[str] = []
        for cycle in self.cycles:
            lines.append("cycle: " + " -> ".join(cycle))
        for collision in self.collisions:
            lines.append(collision.describe())
        for task_id in self.unowned:
            lines.append(
                f"{task_id} names no file in its description, so it was given the glob "
                "'**' and will be scheduled alone"
            )
        return "\n".join(lines)


def validate(plan: Plan) -> Report:
    cycles = _find_cycles(plan)
    # Reachability is meaningless on a cyclic graph, so stop before the collision check
    # rather than report collisions derived from a broken DAG.
    if cycles:
        return Report(cycles=cycles, unowned=_unowned(plan))

    reachable = _transitive_closure(plan)
    collisions: list[Collision] = []

    for index, left in enumerate(plan.tasks):
        for right in plan.tasks[index + 1 :]:
            if right.id in reachable[left.id] or left.id in reachable[right.id]:
                continue  # ordered by the DAG, so they never run at the same time
            overlaps = overlapping_pairs(list(left.owns), list(right.owns))
            if overlaps:
                collisions.append(
                    Collision(left=left.id, right=right.id, globs=tuple(overlaps))
                )

    return Report(
        collisions=tuple(collisions),
        unowned=_unowned(plan),
    )


def _unowned(plan: Plan) -> tuple[str, ...]:
    return tuple(task.id for task in plan.tasks if task.owns == ("**",))


def _transitive_closure(plan: Plan) -> dict[str, set[str]]:
    """For each task, every task that must finish before it."""
    closure: dict[str, set[str]] = {task.id: set() for task in plan.tasks}

    def resolve(task: Task, stack: set[str]) -> set[str]:
        if closure[task.id]:
            return closure[task.id]
        collected: set[str] = set()
        for dependency in task.depends_on:
            collected.add(dependency)
            if dependency not in stack:
                collected |= resolve(plan.by_id[dependency], stack | {task.id})
        closure[task.id] = collected
        return collected

    for task in plan.tasks:
        resolve(task, set())
    return closure


def _find_cycles(plan: Plan) -> tuple[tuple[str, ...], ...]:
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {task.id: WHITE for task in plan.tasks}
    cycles: list[tuple[str, ...]] = []
    path: list[str] = []

    def walk(task_id: str) -> None:
        colour[task_id] = GREY
        path.append(task_id)
        for dependency in plan.by_id[task_id].depends_on:
            if colour[dependency] == GREY:
                start = path.index(dependency)
                cycles.append(tuple(path[start:]) + (dependency,))
            elif colour[dependency] == WHITE:
                walk(dependency)
        path.pop()
        colour[task_id] = BLACK

    for task in plan.tasks:
        if colour[task.id] == WHITE:
            walk(task.id)
    return tuple(cycles)
