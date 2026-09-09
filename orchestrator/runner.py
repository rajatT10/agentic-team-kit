"""Execute a schedule: worktree per task, agents in parallel, tests as the exit condition.

The loop per task is deliberately dumb, because the interesting judgement already happened
upstream. Give the agent its brief, let it work in its own checkout, run the verification
command, and hand the failure output back for a bounded number of rounds. A task is done
when the tests say so — never when the agent says so.

Waves run in order. A wave's worktrees are cut from the integration branch, so each wave
sees everything merged before it, and a wave that does not fully succeed stops the run
rather than letting later tasks build on a broken base.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .agent import AgentRun, build_prompt, run_agent
from .config import RunConfig
from .model import Plan
from .schedule import Assignment, Schedule, Wave, build_schedule
from .worktree import (
    Worktree,
    create_worktree,
    ensure_branch,
    git,
    merge_branch,
    remove_worktree,
)


class Status(str, Enum):
    COMPLETED = "completed"  # verified and merged
    HELD = "held"  # verified, but withheld for human review
    FAILED = "failed"  # rounds exhausted, tests still failing
    ERRORED = "errored"  # the agent could not be run at all
    CONFLICTED = "conflicted"  # verified, but would not merge
    SKIPPED = "skipped"  # an earlier wave stopped the run


@dataclass
class TaskOutcome:
    task_id: str
    status: Status
    rounds: int = 0
    detail: str = ""
    branch: str = ""
    head: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (Status.COMPLETED, Status.HELD)


@dataclass
class WaveOutcome:
    index: int
    outcomes: list[TaskOutcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(outcome.ok for outcome in self.outcomes)


@dataclass
class RunResult:
    feature: str
    integration_branch: str
    waves: list[WaveOutcome] = field(default_factory=list)

    @property
    def outcomes(self) -> list[TaskOutcome]:
        return [outcome for wave in self.waves for outcome in wave.outcomes]

    @property
    def ok(self) -> bool:
        return all(wave.ok for wave in self.waves)

    def summary(self) -> str:
        rows = [
            f"  {o.task_id:<6} {o.status.value:<11} rounds={o.rounds}"
            + (f"  {o.detail}" if o.detail else "")
            for o in self.outcomes
        ]
        head = (
            f"{self.feature}: "
            f"{sum(1 for o in self.outcomes if o.ok)}/{len(self.outcomes)} tasks ok "
            f"on {self.integration_branch}"
        )
        return "\n".join([head, *rows])


def run_feature(
    plan: Plan,
    config: RunConfig,
    repo: str | Path = ".",
    *,
    on_event=None,
) -> RunResult:
    """Run every wave of `plan`. Raises `PlanError` if the plan is not safe to schedule."""
    repo = Path(repo).resolve()
    schedule: Schedule = build_schedule(plan, worktree_root=config.worktree_root)
    emit = on_event or (lambda *_args, **_kwargs: None)

    base = git("rev-parse", config.base_ref, cwd=repo).stdout.strip()
    ensure_branch(repo, config.integration_branch, base)

    result = RunResult(feature=plan.feature, integration_branch=config.integration_branch)
    stopped = False

    for wave in schedule.waves:
        if stopped:
            result.waves.append(
                WaveOutcome(
                    index=wave.index,
                    outcomes=[
                        TaskOutcome(
                            task_id=assignment.task_id,
                            status=Status.SKIPPED,
                            detail="an earlier wave did not complete",
                        )
                        for assignment in wave.assignments
                    ],
                )
            )
            continue

        emit("wave-start", wave=wave)
        outcome = _run_wave(plan, wave, config, repo, emit)
        result.waves.append(outcome)
        emit("wave-end", wave=wave, outcome=outcome)

        if not outcome.ok:
            stopped = True

    return result


def _run_wave(
    plan: Plan, wave: Wave, config: RunConfig, repo: Path, emit
) -> WaveOutcome:
    workers = max(1, min(config.max_concurrency, len(wave.assignments)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(
            pool.map(
                lambda assignment: _run_task(plan, assignment, config, repo, emit),
                wave.assignments,
            )
        )

    # Merge only after every agent in the wave has stopped writing. Merging as each one
    # finishes would move the integration branch under the others' feet.
    for outcome in outcomes:
        if outcome.status is not Status.COMPLETED:
            continue
        merged, detail = merge_branch(
            repo,
            into=config.integration_branch,
            branch=outcome.branch,
            message=f"Merge {outcome.task_id} ({plan.feature})",
        )
        if not merged:
            # Disjoint `owns` was proven before the run, so this means the agents touched
            # something outside their globs — a lockfile, a generated file, a registry.
            outcome.status = Status.CONFLICTED
            outcome.detail = f"merge into {config.integration_branch} conflicted: {detail}"
            emit("merge-conflict", outcome=outcome)
        else:
            emit("merged", outcome=outcome)

    if not config.keep_worktrees:
        for assignment in wave.assignments:
            remove_worktree(repo, assignment.worktree)

    return WaveOutcome(index=wave.index, outcomes=outcomes)


def _run_task(
    plan: Plan, assignment: Assignment, config: RunConfig, repo: Path, emit
) -> TaskOutcome:
    task = plan.by_id[assignment.task_id]
    outcome = TaskOutcome(
        task_id=task.id, status=Status.FAILED, branch=assignment.branch
    )

    try:
        tree = create_worktree(
            repo,
            assignment.worktree,
            branch=assignment.branch,
            base=config.integration_branch,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a task outcome, not a crash
        outcome.status = Status.ERRORED
        outcome.detail = f"could not create worktree: {exc}"
        return outcome

    feedback = ""
    for round_number in range(1, config.rounds + 1):
        outcome.rounds = round_number
        emit("round-start", task_id=task.id, round=round_number)

        prompt = build_prompt(
            plan,
            task,
            verify_command=config.verify_display(),
            feedback=feedback,
            round_number=round_number,
        )
        run: AgentRun = run_agent(
            config.agent,
            prompt,
            cwd=tree.path,
            task_id=task.id,
            worktree=str(tree.path),
        )

        if run.timed_out:
            outcome.status = Status.ERRORED
            outcome.detail = (
                f"agent timed out after {config.agent.timeout_seconds}s"
            )
            return outcome
        if run.exit_code == 127:
            # The CLI is not installed. Retrying cannot help, and burning the remaining
            # rounds on it would bury the real cause under identical failures.
            outcome.status = Status.ERRORED
            outcome.detail = run.stderr.strip()
            return outcome

        tree.commit_all(
            config.commit_message_template.format(task_id=task.id, title=task.title)
        )
        outcome.head = tree.head()

        verdict, detail = _verify(tree, config)
        emit("round-end", task_id=task.id, round=round_number, passed=verdict)

        if verdict:
            if task.requires_human_review and config.stop_on_review_required:
                outcome.status = Status.HELD
                outcome.detail = (
                    "verified, held for human review before merge "
                    "(requires_human_review)"
                )
            else:
                outcome.status = Status.COMPLETED
                outcome.detail = ""
            return outcome

        feedback = detail
        outcome.detail = detail

    outcome.status = Status.FAILED
    outcome.detail = f"still failing after {config.rounds} round(s):\n{feedback}"[:4000]
    return outcome


def _verify(tree: Worktree, config: RunConfig) -> tuple[bool, str]:
    """Run the verification command in the worktree.

    With no command configured there is nothing to check, and saying "passed" would be a
    lie the rest of the run depends on — so the run is refused instead.
    """
    if not config.verify_command:
        return False, (
            "no `verify.command` is configured, so there is no way to tell whether this "
            "task is done; set one in .agentteam/config.json"
        )

    try:
        result = subprocess.run(
            list(config.verify_command),
            cwd=str(tree.path),
            capture_output=True,
            text=True,
            timeout=config.verify_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return False, f"verification timed out after {config.verify_timeout_seconds}s"
    except FileNotFoundError as exc:
        return False, f"verification command not found: {exc}"

    if result.returncode == 0:
        return True, ""
    combined = (result.stdout + "\n" + result.stderr).strip()
    return False, combined[-4000:]
