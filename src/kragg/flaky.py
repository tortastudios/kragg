"""Flaky-test detection, kept out of the inner loop.

Passive detection mines the run journal kragg already writes: a gate that both
passed and failed at the *same* git sha is nondeterministic (same input,
different output). It costs nothing — no re-running — because the data is
already there. Only clean-tree runs are compared: a sha says nothing about
uncommitted edits, so dirty runs (and pre-this-field journal entries) are
ignored to avoid mistaking an edit-and-rerun for flakiness. The active,
Meta-style re-run mode lives alongside it for cron/CI use, never as a gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kragg.environment import ProjectEnvironment
from kragg.parsers import parse_failed_test_ids
from kragg.policy import KraggPolicy
from kragg.runner import run_command


@dataclass(frozen=True)
class FlakyGate:
    """A gate that flipped pass/fail on an unchanged commit."""

    name: str
    sha: str
    passed: int
    failed: int


@dataclass
class _Tally:
    sha: str
    name: str
    passed: int = 0
    failed: int = 0


def passive_flaky(runs: list[dict[str, Any]]) -> tuple[FlakyGate, ...]:
    """Gates that both passed and failed at the same sha across the journal."""
    flaky = [
        FlakyGate(tally.name, tally.sha, tally.passed, tally.failed)
        for tally in _tally(runs).values()
        if tally.passed > 0 and tally.failed > 0
    ]
    return tuple(sorted(flaky, key=lambda gate: gate.failed, reverse=True))


def render_passive(flaky: tuple[FlakyGate, ...]) -> list[str]:
    """Render passive flaky findings as token-efficient lines."""
    if not flaky:
        return ["no flaky gates in recent history"]
    lines = [f"flaky: {len(flaky)} gates flipped on an unchanged commit"]
    for gate in flaky:
        lines.append(
            f"  {gate.name} @ {gate.sha}: {gate.passed} pass / {gate.failed} fail"
        )
    return lines


def _tally(runs: list[dict[str, Any]]) -> dict[str, _Tally]:
    tallies: dict[str, _Tally] = {}
    for run in runs:
        sha = run.get("git_sha")
        gates = run.get("gates")
        if run.get("git_dirty") is not False:
            continue
        if not isinstance(sha, str) or not isinstance(gates, list):
            continue
        for gate in gates:
            if isinstance(gate, dict):
                _record(tallies, sha, gate)
    return tallies


def _record(tallies: dict[str, _Tally], sha: str, gate: dict[Any, Any]) -> None:
    if gate.get("skipped"):
        return
    name = str(gate.get("name", ""))
    tally = tallies.setdefault(f"{sha}::{name}", _Tally(sha, name))
    if gate.get("passed"):
        tally.passed += 1
    else:
        tally.failed += 1


@dataclass(frozen=True)
class FlakyTest:
    """A test that failed intermittently across repeated runs."""

    test_id: str
    failures: int
    runs: int

    @property
    def ratio(self) -> float:
        return self.failures / self.runs if self.runs else 0.0


def run_reruns(
    root: Path,
    env: ProjectEnvironment,
    policy: KraggPolicy,
    count: int,
) -> tuple[FlakyTest, ...]:
    """Run the test suite ``count`` times and rank tests by failure ratio."""
    failed_per_run = [_run_once(root, env, policy) for _ in range(count)]
    return aggregate_reruns(failed_per_run)


def aggregate_reruns(failed_per_run: list[list[str]]) -> tuple[FlakyTest, ...]:
    """Flag tests that failed in some-but-not-all runs (intermittent)."""
    runs = len(failed_per_run)
    counts: dict[str, int] = {}
    for failed in failed_per_run:
        for test_id in set(failed):
            counts[test_id] = counts.get(test_id, 0) + 1
    flaky = [
        FlakyTest(test_id, failures, runs)
        for test_id, failures in counts.items()
        if 0 < failures < runs
    ]
    return tuple(sorted(flaky, key=lambda test: test.failures, reverse=True))


def render_reruns(tests: tuple[FlakyTest, ...], count: int) -> list[str]:
    """Render active-rerun flaky findings as token-efficient lines."""
    if not tests:
        return [f"no flaky tests across {count} runs"]
    lines = [f"flaky: {len(tests)} tests failed intermittently across {count} runs"]
    for test in tests:
        lines.append(
            f"  {test.test_id}: {test.failures}/{test.runs} failed ({test.ratio:.0%})"
        )
    return lines


def _run_once(root: Path, env: ProjectEnvironment, policy: KraggPolicy) -> list[str]:
    command = env.module_command("pytest", *policy.test_paths, "-q")
    return parse_failed_test_ids(run_command("pytest", command, root).stdout)
