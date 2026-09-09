"""How a dev agent gets invoked, and what it is told.

The runner never imports a vendor SDK. An agent is a command template with placeholders,
so the same task plan drives Claude Code, Cursor, Antigravity or a shell script, and
swapping between them is a config change rather than a code change. That is the whole
portability story: the artifacts are plain files, and the agent is a subprocess.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .model import Plan, Task

# Starting points for the CLIs people actually run. Each takes a prompt on the command
# line and works in its current directory, which is the worktree the runner puts it in.
PRESETS: dict[str, list[str]] = {
    "claude": ["claude", "-p", "{prompt}"],
    "cursor": ["cursor-agent", "-p", "{prompt}"],
    "codex": ["codex", "exec", "{prompt}"],
    "gemini": ["gemini", "-p", "{prompt}"],
    # Useful in tests and dry runs: proves the wiring without spending a token.
    "echo": ["/bin/sh", "-c", "echo {prompt}"],
}


@dataclass(frozen=True)
class AgentSpec:
    """A command template plus the limits it runs under."""

    command: tuple[str, ...]
    timeout_seconds: int = 1800
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_preset(cls, name: str, **overrides) -> "AgentSpec":
        if name not in PRESETS:
            known = ", ".join(sorted(PRESETS))
            raise ValueError(f"unknown agent preset {name!r}; known presets: {known}")
        return cls(command=tuple(PRESETS[name]), **overrides)

    def render(self, prompt: str, **fields: str) -> list[str]:
        values = {"prompt": prompt, **fields}
        return [part.format(**values) for part in self.command]


@dataclass(frozen=True)
class AgentRun:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool = False

    def tail(self, limit: int = 4000) -> str:
        """The end of the output — where a failure's actual cause usually is."""
        combined = (self.stdout + "\n" + self.stderr).strip()
        return combined[-limit:]


def run_agent(spec: AgentSpec, prompt: str, cwd: str | Path, **fields: str) -> AgentRun:
    argv = spec.render(prompt, **fields)
    started = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
            env=_environment(spec),
        )
    except subprocess.TimeoutExpired as exc:
        return AgentRun(
            ok=False,
            exit_code=-1,
            stdout=_decode(exc.stdout),
            stderr=_decode(exc.stderr),
            seconds=time.monotonic() - started,
            timed_out=True,
        )
    except FileNotFoundError as exc:
        # A missing CLI is a setup problem, and saying so beats a stack trace nested
        # three layers into a thread pool.
        return AgentRun(
            ok=False,
            exit_code=127,
            stdout="",
            stderr=f"agent command not found: {argv[0]!r} ({exc})",
            seconds=time.monotonic() - started,
        )

    return AgentRun(
        ok=result.returncode == 0,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        seconds=time.monotonic() - started,
    )


def _environment(spec: AgentSpec) -> dict[str, str] | None:
    if not spec.env:
        return None
    import os

    merged = dict(os.environ)
    merged.update(spec.env)
    return merged


def _decode(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def build_prompt(
    plan: Plan,
    task: Task,
    *,
    verify_command: str = "",
    feedback: str = "",
    round_number: int = 1,
) -> str:
    """The brief handed to a dev agent for one task.

    Deliberately narrow. The agent is told exactly which paths it owns and that anything
    else is another agent's concurrently — a boundary it cannot infer from the repository,
    because the other agent's work does not exist on disk yet.
    """
    owned = "\n".join(f"  - {glob}" for glob in task.owns)
    lines = [
        f"You are implementing one task from the feature `{plan.feature}`.",
        "",
        f"## Task {task.id}: {task.title}",
    ]

    if task.notes:
        lines += ["", task.notes]

    lines += [
        "",
        "## Files you own",
        "",
        "You may create or modify files matching these globs, and nothing else:",
        "",
        owned,
        "",
        "Other tasks are being implemented at the same time in separate checkouts. Files "
        "outside your globs belong to them; editing one will be discarded at merge time "
        "and may break their work. If the task cannot be completed within these paths, "
        "stop and say so rather than widening the change.",
    ]

    if task.covers:
        lines += [
            "",
            "## Acceptance criteria this task must satisfy",
            "",
            *(f"  - {item}" for item in task.covers),
        ]

    context = [
        ("requirements", plan.requirements),
        ("design", plan.design),
    ]
    referenced = [f"  - {label}: {path}" for label, path in context if path]
    if referenced:
        lines += ["", "## Context to read first", "", *referenced]

    if verify_command:
        lines += [
            "",
            "## Definition of done",
            "",
            f"`{verify_command}` passes. That is the exit condition — not your own "
            "judgement that the code looks right.",
        ]

    if feedback:
        lines += [
            "",
            f"## Round {round_number}: the previous attempt failed",
            "",
            "This is what the verification step reported. Fix the cause; do not modify "
            "or delete the test to make it pass.",
            "",
            "```",
            feedback.strip(),
            "```",
        ]

    return "\n".join(lines)


def format_command(command: tuple[str, ...] | list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)
