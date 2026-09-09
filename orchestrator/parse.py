"""Load a task plan from either supported format.

Two formats exist because two task-splitters do: this kit's `tasks.json`, which states
file ownership as globs, and GitHub Spec Kit's `tasks.md`, which states it as a file path
buried in the task's prose description plus an advisory `[P]` marker.

The Spec Kit reader is deliberately a lossy import, not a peer format. It recovers what
ownership it can from the description and flags the rest, so a Spec Kit plan can be run
through the same safety check instead of being taken on trust.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .model import Plan, PlanError, Task

# `- [ ] T005 [P] [US1] Implement auth middleware in src/middleware/auth.py`
_SPECKIT_LINE = re.compile(
    r"^\s*-\s*\[(?P<done>[ xX])\]\s*"
    r"(?P<id>T\d+)\s*"
    r"(?P<markers>(?:\[[^\]]+\]\s*)*)"
    r"(?P<description>.+?)\s*$"
)
_MARKER = re.compile(r"\[([^\]]+)\]")
# A path-shaped token: has a slash, or a file extension, and no spaces.
_PATH_TOKEN = re.compile(r"(?:[\w.\-]+/)+[\w.\-*]+|[\w\-]+\.[A-Za-z0-9]{1,6}")


def load_plan(path: str | Path) -> Plan:
    """Read a plan, dispatching on file type."""
    path = Path(path)
    if not path.exists():
        raise PlanError(f"no plan at {path}")
    if path.suffix == ".json":
        return load_tasks_json(path)
    if path.suffix == ".md":
        return load_speckit_tasks_md(path)
    raise PlanError(f"unsupported plan format {path.suffix!r}; expected .json or .md")


def load_tasks_json(path: str | Path) -> Plan:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PlanError(f"{path} must contain a JSON object")

    entries = raw.get("tasks")
    if not isinstance(entries, list) or not entries:
        raise PlanError(f"{path} has no tasks")

    tasks = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise PlanError(f"{path}: tasks[{index}] is not an object")
        tasks.append(
            Task(
                id=str(entry.get("id", "")),
                title=str(entry.get("title", "")),
                owns=tuple(_string_list(entry.get("owns"), path, index, "owns")),
                depends_on=tuple(
                    _string_list(entry.get("depends_on"), path, index, "depends_on")
                ),
                covers=tuple(_string_list(entry.get("covers"), path, index, "covers")),
                requires_human_review=bool(entry.get("requires_human_review", False)),
                notes=str(entry.get("notes", "")),
            )
        )

    return Plan(
        feature=str(raw.get("feature", path.parent.name)),
        tasks=tuple(tasks),
        mode=str(raw.get("mode", "sequential")),
        requirements=str(raw.get("requirements", "")),
        design=str(raw.get("design", "")),
        source=str(path),
    )


def load_speckit_tasks_md(path: str | Path) -> Plan:
    """Import a Spec Kit `tasks.md` checklist as a plan.

    Ownership is recovered from path-shaped tokens in each task's description. A task
    whose description names no file gets a sentinel glob that collides with everything,
    which forces it to be scheduled alone rather than silently treated as safe.
    """
    path = Path(path)
    tasks: list[Task] = []
    # Spec Kit orders work with phase barriers: a task without `[P]` may not overlap the
    # `[P]` run before it, and everything after it waits. Modelling that as "depends on
    # the previous line" would be both wrong and needlessly serial.
    barrier: str | None = None
    since_barrier: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        match = _SPECKIT_LINE.match(line)
        if not match:
            continue

        markers = _MARKER.findall(match.group("markers") or "")
        description = match.group("description")
        parallel = any(marker.strip().upper() == "P" for marker in markers)
        owns = _paths_in(description) or ("**",)

        task_id = match.group("id")
        if parallel:
            # Independent of its siblings, but still downstream of the open barrier.
            depends_on = (barrier,) if barrier else ()
        elif since_barrier:
            # A barrier closes the parallel run before it.
            depends_on = tuple(since_barrier)
        else:
            depends_on = (barrier,) if barrier else ()
        tasks.append(
            Task(
                id=task_id,
                title=description,
                owns=owns,
                depends_on=depends_on,
                covers=tuple(
                    marker for marker in markers if marker.strip().upper() != "P"
                ),
                notes="imported from Spec Kit tasks.md",
            )
        )

        if parallel:
            since_barrier.append(task_id)
        else:
            barrier = task_id
            since_barrier = []

    if not tasks:
        raise PlanError(f"{path} contained no task lines")

    return Plan(
        feature=path.parent.name,
        tasks=tuple(tasks),
        mode="parallel",
        source=str(path),
    )


def _paths_in(description: str) -> tuple[str, ...]:
    found: list[str] = []
    for token in _PATH_TOKEN.findall(description):
        cleaned = token.strip(".,;:()[]")
        if cleaned and cleaned not in found:
            found.append(cleaned)
    return tuple(found)


def _string_list(value: object, path: Path, index: int, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PlanError(f"{path}: tasks[{index}].{field} must be a list of strings")
    return list(value)
