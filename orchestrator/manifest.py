"""`test-manifest.json`: acceptance criteria mapped to individual tests.

This is what turns "the suite passed" into "AC-3 passed". A dev agent's exit condition
becomes the specific tests tied to its task's `covers` list, so a task cannot be reported
done because some unrelated test went green, and a QA bug filed mid-loop is a new entry in
this file rather than a paragraph someone has to interpret.

The schema is `.claude/skills/qa-test-plan/references/test-manifest-schema.md`.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Noise that changes run to run and would otherwise make every failure look novel.
_VOLATILE = [
    re.compile(r"\b\d+\.\d+s\b"),  # durations
    re.compile(r"0x[0-9a-fA-F]+"),  # object addresses
    re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*"),  # timestamps
    re.compile(r"/tmp/[^\s'\"]+"),  # per-run temp paths
]


class ManifestError(ValueError):
    """The manifest is malformed or does not match the plan it is meant to verify."""


@dataclass(frozen=True)
class TestEntry:
    ac_id: str
    file: str
    test_name: str
    status: str = "red"
    found_in_round: int = 0

    @property
    def is_red(self) -> bool:
        """Red tests are the exit condition; green ones guard against regressions."""
        return self.status == "red"

    @property
    def selector(self) -> str:
        return f"{self.file}::{self.test_name}" if self.test_name else self.file


@dataclass(frozen=True)
class Manifest:
    feature: str
    single_test_command: str
    tests: tuple[TestEntry, ...]
    framework: str = ""
    requirements: str = ""
    source: str = ""

    def for_criteria(self, covers: tuple[str, ...] | list[str]) -> tuple[TestEntry, ...]:
        wanted = set(covers)
        return tuple(entry for entry in self.tests if entry.ac_id in wanted)

    @property
    def regression_tests(self) -> tuple[TestEntry, ...]:
        return tuple(entry for entry in self.tests if not entry.is_red)


@dataclass(frozen=True)
class TestResult:
    entry: TestEntry
    passed: bool
    output: str = ""

    @property
    def signature(self) -> str:
        """A stable fingerprint of *how* this test failed.

        Two rounds producing the same signature means the agent changed nothing that
        mattered, which is worth escalating on rather than spending another round.
        """
        if self.passed:
            return ""
        text = self.output
        for pattern in _VOLATILE:
            text = pattern.sub("", text)
        digest = hashlib.sha1(text.strip().encode("utf-8", "replace"))
        return f"{self.entry.ac_id}:{digest.hexdigest()[:12]}"


@dataclass(frozen=True)
class VerificationReport:
    results: tuple[TestResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failures(self) -> tuple[TestResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    @property
    def signature(self) -> str:
        return "|".join(sorted(result.signature for result in self.failures))

    def describe(self) -> str:
        if self.passed:
            return "all acceptance criteria pass"
        lines = []
        for result in self.failures:
            lines.append(f"{result.entry.ac_id} FAILED ({result.entry.selector})")
            if result.output:
                lines.append(result.output.strip()[-1500:])
        return "\n".join(lines)

    def by_criterion(self) -> dict[str, bool]:
        return {result.entry.ac_id: result.passed for result in self.results}


def load_manifest(path: str | Path) -> Manifest:
    path = Path(path)
    if not path.exists():
        raise ManifestError(f"no manifest at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"{path} must contain a JSON object")

    command = raw.get("single_test_command", "")
    if not isinstance(command, str) or not command.strip():
        raise ManifestError(f"{path}: `single_test_command` is required")
    if not _PLACEHOLDER.search(command):
        raise ManifestError(
            f"{path}: `single_test_command` must contain a placeholder — one of "
            "{test}, {file} or {test_name} — so a single test can be run on its own"
        )

    entries_raw = raw.get("tests")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise ManifestError(f"{path} lists no tests")

    entries: list[TestEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(entries_raw):
        if not isinstance(item, dict):
            raise ManifestError(f"{path}: tests[{index}] is not an object")
        ac_id = str(item.get("ac_id", "")).strip()
        if not ac_id:
            raise ManifestError(f"{path}: tests[{index}] has no ac_id")
        if ac_id in seen:
            # The schema requires exactly one entry per criterion. A duplicate means one
            # of them is silently ignored, and which one would depend on ordering.
            raise ManifestError(f"{path}: {ac_id} appears more than once")
        seen.add(ac_id)
        status = str(item.get("status", "red"))
        if status not in {"red", "green"}:
            raise ManifestError(
                f"{path}: tests[{index}].status must be 'red' or 'green', got {status!r}"
            )
        entries.append(
            TestEntry(
                ac_id=ac_id,
                file=str(item.get("file", "")),
                test_name=str(item.get("test_name", "")),
                status=status,
                found_in_round=int(item.get("found_in_round", 0)),
            )
        )

    return Manifest(
        feature=str(raw.get("feature", path.parent.name)),
        single_test_command=command,
        tests=tuple(entries),
        framework=str(raw.get("framework", "")),
        requirements=str(raw.get("requirements", "")),
        source=str(path),
    )


_PLACEHOLDER = re.compile(r"\{(test|file|test_name)\}")


def render_command(manifest: Manifest, entry: TestEntry) -> list[str]:
    rendered = manifest.single_test_command.format(
        test=entry.selector, file=entry.file, test_name=entry.test_name
    )
    return shlex.split(rendered)


def run_tests(
    manifest: Manifest,
    entries: tuple[TestEntry, ...] | list[TestEntry],
    cwd: str | Path,
    timeout: int = 600,
) -> VerificationReport:
    """Run each entry on its own so a failure is attributable to one criterion."""
    results: list[TestResult] = []
    for entry in entries:
        try:
            completed = subprocess.run(
                render_command(manifest, entry),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (completed.stdout + "\n" + completed.stderr).strip()
            results.append(
                TestResult(
                    entry=entry, passed=completed.returncode == 0, output=output[-4000:]
                )
            )
        except subprocess.TimeoutExpired:
            results.append(
                TestResult(
                    entry=entry,
                    passed=False,
                    output=f"timed out after {timeout}s",
                )
            )
        except FileNotFoundError as exc:
            results.append(
                TestResult(entry=entry, passed=False, output=f"command not found: {exc}")
            )
    return VerificationReport(results=tuple(results))


def cross_check(manifest: Manifest, plan) -> list[str]:
    """Warn where the manifest and the task plan disagree about which ACs exist.

    Neither side is authoritative on its own: a criterion with no test cannot be verified,
    and a test for a criterion no task covers will never be anyone's exit condition.
    """
    planned = {ac for task in plan.tasks for ac in task.covers}
    tested = {entry.ac_id for entry in manifest.tests}
    notes = []
    for missing in sorted(planned - tested):
        if missing.startswith("AC-"):
            notes.append(f"{missing} is covered by a task but has no test in the manifest")
    for orphan in sorted(tested - planned):
        notes.append(f"{orphan} has a test but no task covers it")
    return notes
