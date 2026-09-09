"""Deterministic scheduling for the dev-agent phase of the kit.

Everything here is plain Python with no model in the loop: given a task plan, decide what
may run concurrently and refuse the plan outright when that cannot be established. The
agents do the work; this decides what they are allowed to touch and when.
"""

from .agent import AgentRun, AgentSpec, build_prompt, run_agent
from .config import ConfigError, RunConfig, default_config, load_config, write_template
from .globset import globs_intersect, overlapping_pairs
from .manifest import (
    Manifest,
    ManifestError,
    TestEntry,
    VerificationReport,
    cross_check,
    load_manifest,
    run_tests,
)
from .model import Plan, PlanError, Task
from .parse import load_plan, load_speckit_tasks_md, load_tasks_json
from .review import DiffStat, build_description, collect_diff
from .runner import RunResult, Status, TaskOutcome, WaveOutcome, run_feature
from .schedule import Assignment, Schedule, Wave, build_schedule
from .validate import Collision, Report, validate

__all__ = [
    "AgentRun",
    "AgentSpec",
    "Assignment",
    "Collision",
    "ConfigError",
    "DiffStat",
    "Manifest",
    "ManifestError",
    "Plan",
    "PlanError",
    "Report",
    "RunConfig",
    "RunResult",
    "Schedule",
    "Status",
    "Task",
    "TaskOutcome",
    "TestEntry",
    "VerificationReport",
    "Wave",
    "WaveOutcome",
    "build_description",
    "build_prompt",
    "build_schedule",
    "collect_diff",
    "cross_check",
    "default_config",
    "globs_intersect",
    "load_config",
    "load_manifest",
    "load_plan",
    "load_speckit_tasks_md",
    "load_tasks_json",
    "overlapping_pairs",
    "run_agent",
    "run_feature",
    "run_tests",
    "validate",
    "write_template",
]
