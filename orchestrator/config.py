"""Runtime policy: which agent, which verification command, how many rounds.

Kept out of `tasks.json` on purpose. The task plan describes the work and is reviewed by a
human at the gate; this describes how the machine executes it and changes for reasons that
have nothing to do with the feature — a different agent CLI, a slower test suite, a
tighter budget.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .agent import PRESETS, AgentSpec

DEFAULT_PATH = ".agentteam/config.json"


class ConfigError(ValueError):
    """The config is unusable. Raised eagerly, before any agent is dispatched."""


@dataclass(frozen=True)
class RunConfig:
    agent: AgentSpec
    verify_command: tuple[str, ...] = ()
    verify_timeout_seconds: int = 600
    max_rounds: int = 3
    integration_branch: str = "agent/integration"
    base_ref: str = "HEAD"
    worktree_root: str = ".worktrees"
    max_concurrency: int = 4
    commit_message_template: str = "{task_id}: {title}"
    keep_worktrees: bool = False
    source: str = "<defaults>"

    # A task that lands in a danger zone is held even when its tests pass, which is what
    # `requires_human_review` in the task plan is for.
    stop_on_review_required: bool = True

    def verify_display(self) -> str:
        return " ".join(self.verify_command)

    @property
    def rounds(self) -> int:
        return max(1, self.max_rounds)


def default_config() -> RunConfig:
    return RunConfig(agent=AgentSpec.from_preset("claude"))


def load_config(path: str | Path | None = None) -> RunConfig:
    """Read config from `path`, falling back to defaults when there is no file."""
    if path is None:
        candidate = Path(DEFAULT_PATH)
        if not candidate.exists():
            return default_config()
        path = candidate

    path = Path(path)
    if not path.exists():
        raise ConfigError(f"no config at {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object")

    return _from_mapping(raw, source=str(path))


def _from_mapping(raw: dict, *, source: str) -> RunConfig:
    agent_raw = raw.get("agent", {})
    if not isinstance(agent_raw, dict):
        raise ConfigError("`agent` must be an object")

    command = agent_raw.get("command")
    preset = agent_raw.get("preset")
    if command is not None:
        if not isinstance(command, list) or not all(
            isinstance(part, str) for part in command
        ):
            raise ConfigError("`agent.command` must be a list of strings")
        if not command:
            raise ConfigError("`agent.command` must not be empty")
        if not any("{prompt}" in part for part in command):
            raise ConfigError(
                "`agent.command` must contain a {prompt} placeholder, otherwise the "
                "agent is invoked with no task to work on"
            )
        agent = AgentSpec(
            command=tuple(command),
            timeout_seconds=int(agent_raw.get("timeout_seconds", 1800)),
            env=dict(agent_raw.get("env", {})),
        )
    else:
        name = preset or "claude"
        if name not in PRESETS:
            raise ConfigError(
                f"unknown agent preset {name!r}; known presets: "
                + ", ".join(sorted(PRESETS))
            )
        agent = AgentSpec.from_preset(
            name,
            timeout_seconds=int(agent_raw.get("timeout_seconds", 1800)),
            env=dict(agent_raw.get("env", {})),
        )

    verify_raw = raw.get("verify", {})
    if not isinstance(verify_raw, dict):
        raise ConfigError("`verify` must be an object")
    verify_command = verify_raw.get("command", [])
    if not isinstance(verify_command, list) or not all(
        isinstance(part, str) for part in verify_command
    ):
        raise ConfigError("`verify.command` must be a list of strings")

    policy = raw.get("policy", {})
    if not isinstance(policy, dict):
        raise ConfigError("`policy` must be an object")

    return RunConfig(
        agent=agent,
        verify_command=tuple(verify_command),
        verify_timeout_seconds=int(verify_raw.get("timeout_seconds", 600)),
        max_rounds=int(policy.get("max_rounds", 3)),
        integration_branch=str(policy.get("integration_branch", "agent/integration")),
        base_ref=str(policy.get("base_ref", "HEAD")),
        worktree_root=str(policy.get("worktree_root", ".worktrees")),
        max_concurrency=int(policy.get("max_concurrency", 4)),
        commit_message_template=str(
            policy.get("commit_message_template", "{task_id}: {title}")
        ),
        keep_worktrees=bool(policy.get("keep_worktrees", False)),
        stop_on_review_required=bool(policy.get("stop_on_review_required", True)),
        source=source,
    )


TEMPLATE = {
    "agent": {
        "preset": "claude",
        "timeout_seconds": 1800,
        "_comment": (
            "Use `preset` for a known CLI (claude, cursor, codex, gemini, echo), or "
            "replace it with `command` for anything else — a list of argv parts, one of "
            "which contains the {prompt} placeholder."
        ),
    },
    "verify": {
        "command": ["python3", "-m", "unittest", "discover", "-s", "tests"],
        "timeout_seconds": 600,
    },
    "policy": {
        "max_rounds": 3,
        "max_concurrency": 4,
        "integration_branch": "agent/integration",
        "worktree_root": ".worktrees",
        "keep_worktrees": False,
        "stop_on_review_required": True,
    },
}


def write_template(path: str | Path = DEFAULT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(TEMPLATE, indent=2) + "\n", encoding="utf-8")
    return path
