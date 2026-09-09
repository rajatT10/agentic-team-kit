"""Deterministic scheduling for the dev-agent phase of the kit.

Everything here is plain Python with no model in the loop: given a task plan, decide what
may run concurrently and refuse the plan outright when that cannot be established. The
agents do the work; this decides what they are allowed to touch and when.
"""

from .globset import globs_intersect, overlapping_pairs
from .model import Plan, PlanError, Task
from .parse import load_plan, load_speckit_tasks_md, load_tasks_json
from .schedule import Assignment, Schedule, Wave, build_schedule
from .validate import Collision, Report, validate

__all__ = [
    "Assignment",
    "Collision",
    "Plan",
    "PlanError",
    "Report",
    "Schedule",
    "Task",
    "Wave",
    "build_schedule",
    "globs_intersect",
    "load_plan",
    "load_speckit_tasks_md",
    "load_tasks_json",
    "overlapping_pairs",
    "validate",
]
