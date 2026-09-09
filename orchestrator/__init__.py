"""Deterministic scheduling for the dev-agent phase of the kit.

Everything here is plain Python with no model in the loop: given a task plan, decide what
may run concurrently and refuse the plan outright when that cannot be established. The
agents do the work; this decides what they are allowed to touch and when.
"""

from .agent import AgentRun, AgentSpec, build_prompt, run_agent
from .config import ConfigError, RunConfig, default_config, load_config, write_template
from .globset import globs_intersect, overlapping_pairs
from .model import Plan, PlanError, Task
from .parse import load_plan, load_speckit_tasks_md, load_tasks_json
from .runner import RunResult, Status, TaskOutcome, WaveOutcome, run_feature
from .schedule import Assignment, Schedule, Wave, build_schedule
from .validate import Collision, Report, validate

__all__ = [
    "AgentRun",
    "AgentSpec",
    "Assignment",
    "Collision",
    "ConfigError",
    "Plan",
    "PlanError",
    "Report",
    "RunConfig",
    "RunResult",
    "Schedule",
    "Status",
    "Task",
    "TaskOutcome",
    "Wave",
    "WaveOutcome",
    "build_prompt",
    "build_schedule",
    "default_config",
    "globs_intersect",
    "load_config",
    "load_plan",
    "load_speckit_tasks_md",
    "load_tasks_json",
    "overlapping_pairs",
    "run_agent",
    "run_feature",
    "validate",
    "write_template",
]
