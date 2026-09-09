"""Turn a finished run into a pull request description.

Deliberately not an agent. Everything a reviewer needs — which tasks ran, which acceptance
criteria are green, what actually changed on disk — is already recorded by the time the run
ends. Asking a model to restate it would add a paraphrasing step that can be wrong, in
front of the one artifact a human reads before approving the change.

What the model wrote is the diff; this describes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import Plan
from .runner import RunResult, Status
from .worktree import git

_STATUS_NOTE = {
    Status.COMPLETED: "merged",
    Status.HELD: "**held for human review** — verified but deliberately not merged",
    Status.FAILED: "**not merged** — verification still failing",
    Status.ESCALATED: "**escalated** — failed identically twice",
    Status.CONFLICTED: "**not merged** — conflicted on the integration branch",
    Status.ERRORED: "**not run** — the agent could not be started",
    Status.SKIPPED: "not attempted — an earlier wave stopped the run",
}


@dataclass(frozen=True)
class DiffStat:
    files: int
    insertions: int
    deletions: int
    paths: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return self.files == 0


def collect_diff(repo: str | Path, base: str, head: str) -> DiffStat:
    """Summarise `base..head` without loading the whole patch into memory."""
    names = git("diff", "--name-only", f"{base}...{head}", cwd=repo).stdout.split()
    numstat = git("diff", "--numstat", f"{base}...{head}", cwd=repo).stdout.splitlines()

    insertions = deletions = 0
    for line in numstat:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, removed, _ = parts[0], parts[1], parts[2]
        # Binary files report "-" rather than a count.
        insertions += int(added) if added.isdigit() else 0
        deletions += int(removed) if removed.isdigit() else 0

    return DiffStat(
        files=len(names),
        insertions=insertions,
        deletions=deletions,
        paths=tuple(sorted(names)),
    )


def build_description(
    plan: Plan,
    result: RunResult,
    diff: DiffStat | None = None,
    *,
    title: str | None = None,
) -> str:
    """Render the PR body. Honest about partial runs rather than only listing wins."""
    lines: list[str] = []
    heading = title or f"{plan.feature}: {_headline(result)}"
    lines += [f"# {heading}", ""]

    if plan.requirements or plan.design:
        refs = [f"- {label}: `{path}`" for label, path in
                (("Requirements", plan.requirements), ("Design", plan.design)) if path]
        lines += ["## Specification", "", *refs, ""]

    lines += ["## Tasks", "", "| Task | Owns | Outcome | Rounds |", "|---|---|---|---|"]
    for outcome in result.outcomes:
        task = plan.by_id.get(outcome.task_id)
        owns = ", ".join(f"`{glob}`" for glob in task.owns) if task else ""
        note = _STATUS_NOTE.get(outcome.status, outcome.status.value)
        title_text = task.title if task else outcome.task_id
        lines.append(
            f"| {outcome.task_id} — {title_text} | {owns} | {note} | {outcome.rounds} |"
        )
    lines.append("")

    criteria = _criteria_table(result)
    if criteria:
        lines += ["## Acceptance criteria", "", *criteria, ""]

    if diff is not None and not diff.empty:
        lines += [
            "## Changes",
            "",
            f"{diff.files} file(s), +{diff.insertions} / −{diff.deletions}",
            "",
            *(f"- `{path}`" for path in diff.paths[:40]),
        ]
        if len(diff.paths) > 40:
            lines.append(f"- …and {len(diff.paths) - 40} more")
        lines.append("")

    blockers = _blockers(plan, result)
    if blockers:
        lines += ["## Not ready to merge", "", *blockers, ""]

    lines += [
        "## How this was produced",
        "",
        f"Tasks were scheduled into {len(result.waves)} wave(s) from `{plan.source or 'tasks.json'}`. "
        "Each ran in its own git worktree against a disjoint set of `owns` globs, verified "
        "against its own acceptance criteria, and merged into "
        f"`{result.integration_branch}` only once green.",
        "",
    ]
    return "\n".join(lines)


def _headline(result: RunResult) -> str:
    done = sum(1 for outcome in result.outcomes if outcome.ok)
    total = len(result.outcomes)
    if result.ok:
        return f"{total} task(s) implemented and verified"
    return f"{done}/{total} task(s) complete"


def _criteria_table(result: RunResult) -> list[str]:
    merged: dict[str, bool] = {}
    owner: dict[str, str] = {}
    for outcome in result.outcomes:
        for ac_id, passed in outcome.criteria.items():
            # A criterion checked by several tasks is only green if it is green everywhere.
            merged[ac_id] = merged.get(ac_id, True) and passed
            owner.setdefault(ac_id, outcome.task_id)
    if not merged:
        return []

    rows = ["| Criterion | Task | Status |", "|---|---|---|"]
    for ac_id in sorted(merged, key=_criterion_sort_key):
        mark = "pass" if merged[ac_id] else "**fail**"
        rows.append(f"| {ac_id} | {owner.get(ac_id, '')} | {mark} |")
    return rows


def _criterion_sort_key(ac_id: str) -> tuple[str, int, str]:
    prefix, _, number = ac_id.partition("-")
    return (prefix, int(number) if number.isdigit() else 0, ac_id)


def _blockers(plan: Plan, result: RunResult) -> list[str]:
    notes = []
    for outcome in result.outcomes:
        if outcome.ok and outcome.status is not Status.HELD:
            continue
        task = plan.by_id.get(outcome.task_id)
        label = f"{outcome.task_id} ({task.title})" if task else outcome.task_id
        detail = outcome.detail.strip().splitlines()
        first = detail[0] if detail else outcome.status.value
        notes.append(f"- **{label}** — {first}")
    return notes
