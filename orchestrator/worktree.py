"""Per-task git worktrees.

Each task in a wave gets its own checkout on its own branch, so two agents writing at the
same time cannot see or clobber each other's uncommitted work. `owns` proves the file sets
are disjoint; the worktree is what makes that proof matter at runtime — without it,
"disjoint" is a claim about intent rather than about the filesystem.

Everything here shells out to git rather than using a library, so the behaviour matches
what a developer would see running the same commands by hand.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    """A git command failed. Carries the command's own stderr, not a paraphrase."""


def git(
    *args: str, cwd: str | Path, check: bool = True, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed in {cwd} "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    return result


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    repo: Path

    def run(self, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
        return git(*args, cwd=self.path, **kwargs)

    def has_changes(self) -> bool:
        return bool(git("status", "--porcelain", cwd=self.path).stdout.strip())

    def commit_all(self, message: str) -> bool:
        """Stage and commit everything. Returns False when there was nothing to commit."""
        if not self.has_changes():
            return False
        git("add", "-A", cwd=self.path)
        git("commit", "-m", message, cwd=self.path)
        return True

    def head(self) -> str:
        return git("rev-parse", "HEAD", cwd=self.path).stdout.strip()


def create_worktree(repo: str | Path, path: str | Path, branch: str, base: str) -> Worktree:
    """Add a worktree at `path` on a new `branch` cut from `base`.

    A leftover worktree from an earlier run is removed first: the alternative is failing
    the whole wave because a previous run was interrupted, which turns a transient problem
    into a manual cleanup chore.
    """
    repo = Path(repo).resolve()
    path = Path(path)
    if not path.is_absolute():
        path = repo / path

    remove_worktree(repo, path, branch=branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    git("worktree", "add", "-b", branch, str(path), base, cwd=repo)
    return Worktree(path=path, branch=branch, repo=repo)


def remove_worktree(repo: str | Path, path: str | Path, branch: str | None = None) -> None:
    """Best-effort teardown. Never raises — cleanup failing must not mask a real result."""
    repo = Path(repo).resolve()
    path = Path(path)
    if not path.is_absolute():
        path = repo / path

    git("worktree", "remove", "--force", str(path), cwd=repo, check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    git("worktree", "prune", cwd=repo, check=False)
    if branch:
        git("branch", "-D", branch, cwd=repo, check=False)


def branch_exists(repo: str | Path, branch: str) -> bool:
    result = git(
        "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=repo, check=False
    )
    return result.returncode == 0


def ensure_branch(repo: str | Path, branch: str, base: str) -> None:
    """Create `branch` at `base` if it does not already exist."""
    if not branch_exists(repo, branch):
        git("branch", branch, base, cwd=repo)


def merge_branch(repo: str | Path, into: str, branch: str, message: str) -> tuple[bool, str]:
    """Merge `branch` into `into` with a merge commit. Returns (merged, detail).

    A conflict here is a finding, not a routine outcome: validation already proved the two
    tasks own disjoint paths, so a conflict means something outside `owns` was touched — a
    lockfile, a generated file, a shared registry. The merge is aborted and the caller is
    told, rather than a half-merged tree being left behind.
    """
    current = git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).stdout.strip()
    try:
        git("checkout", into, cwd=repo)
        result = git(
            "merge", "--no-ff", "-m", message, branch, cwd=repo, check=False
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        git("merge", "--abort", cwd=repo, check=False)
        return False, (result.stdout + result.stderr).strip()
    finally:
        git("checkout", current, cwd=repo, check=False)
