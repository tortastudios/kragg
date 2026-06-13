"""Local run journal: .kragg/history.jsonl, one slim line per check run.

Telemetry must never fail a check: every write path swallows OSError.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict, cast

from kragg.report import ReportPayload

JOURNAL_DIR = ".kragg"
JOURNAL_FILE = "history.jsonl"
MAX_LINES = 1000
KEEP_LINES = 500


class JournalGate(TypedDict):
    name: str
    passed: bool
    skipped: bool
    duration_ms: int
    violation_count: int


class JournalEntry(TypedDict):
    schema_version: int
    ts: str
    command: str
    mode: str
    git_sha: str | None
    passed: bool
    exit_code: int
    duration_ms: int
    gates: list[JournalGate]


def append_run(root: Path, payload: ReportPayload) -> None:
    """Record one run; rotates the file when it grows past MAX_LINES."""
    entry = JournalEntry(
        schema_version=payload["schema_version"],
        ts=payload["started_at"],
        command=payload["command"],
        mode=payload["mode"],
        git_sha=payload["git_sha"],
        passed=payload["passed"],
        exit_code=payload["exit_code"],
        duration_ms=payload["duration_ms"],
        gates=[
            JournalGate(
                name=gate["name"],
                passed=gate["passed"],
                skipped=gate["skipped"],
                duration_ms=gate["duration_ms"],
                violation_count=gate["violation_count"],
            )
            for gate in payload["gates"]
        ],
    )
    path = journal_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
        _rotate(path)
    except OSError:
        return


def read_runs(root: Path, last: int) -> list[dict[str, Any]]:
    """Return the most recent runs, oldest first; tolerates malformed lines."""
    path = journal_path(root)
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    runs: list[dict[str, Any]] = []
    for line in lines[-last:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            runs.append(cast(dict[str, Any], entry))
    return runs


def render_status_lines(runs: list[dict[str, Any]]) -> list[str]:
    """Summarize recorded runs for `kragg status` text output."""
    last = runs[-1]
    lines = [_summary_line(last)]
    failing = _failing_line(last)
    if failing is not None:
        lines.append(failing)
    lines.append(f"pass streak: {_pass_streak(runs)} of last {len(runs)} runs")
    slowest = _slowest_line(last)
    if slowest is not None:
        lines.append(slowest)
    return lines


def _summary_line(last: dict[str, Any]) -> str:
    verdict = "PASS" if last.get("passed") else "FAIL"
    duration = cast(int, last.get("duration_ms", 0)) / 1000
    return (
        f"last run: {verdict} ({last.get('command')}, {last.get('mode')} mode, "
        f"{last.get('ts')}, {duration:.1f}s)"
    )


def _failing_line(last: dict[str, Any]) -> str | None:
    failing = [
        f"{gate.get('name')} ({gate.get('violation_count')} violations)"
        for gate in _gates(last)
        if not gate.get("passed") and not gate.get("skipped")
    ]
    if not failing:
        return None
    return f"failing gates: {', '.join(failing)}"


def _slowest_line(last: dict[str, Any]) -> str | None:
    timed = [g for g in _gates(last) if cast(int, g.get("duration_ms", 0)) > 0]
    if not timed:
        return None
    slowest = max(timed, key=lambda g: cast(int, g.get("duration_ms", 0)))
    seconds = cast(int, slowest.get("duration_ms", 0)) / 1000
    return f"slowest gate: {slowest.get('name')} ({seconds:.1f}s)"


def _pass_streak(runs: list[dict[str, Any]]) -> int:
    streak = 0
    for run in reversed(runs):
        if not run.get("passed"):
            break
        streak += 1
    return streak


def _gates(run: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], run.get("gates", []))


def journal_path(root: Path) -> Path:
    return root / JOURNAL_DIR / JOURNAL_FILE


def _rotate(path: Path) -> None:
    lines = path.read_text().splitlines()
    if len(lines) > MAX_LINES:
        path.write_text("\n".join(lines[-KEEP_LINES:]) + "\n")
