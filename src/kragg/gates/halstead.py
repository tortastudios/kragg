from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from radon.metrics import h_visit

MAX_EFFORT: float = 50_000.0
MAX_DIFFICULTY: float = 30.0
MAX_BUGS: float = 0.4


@dataclass(frozen=True)
class HalsteadViolation:
    """A Halstead metric threshold violation."""

    location: str
    metric: str
    actual: float
    maximum: float


def check_file(path: Path) -> list[HalsteadViolation]:
    """Return Halstead violations for one Python file."""
    code = path.read_text()
    failures: list[HalsteadViolation] = []

    try:
        results = h_visit(code)
    except Exception as exc:
        return [
            HalsteadViolation(
                location=str(path),
                metric=f"could not parse: {exc}",
                actual=1.0,
                maximum=0.0,
            )
        ]

    functions = cast(Any, results).functions
    for func_name, metrics in functions:
        name = f"{path}::{func_name}" if func_name else str(path)
        effort = float(metrics.effort)
        difficulty = float(metrics.difficulty)
        bugs = float(metrics.bugs)

        if effort > MAX_EFFORT:
            failures.append(HalsteadViolation(name, "effort", effort, MAX_EFFORT))
        if difficulty > MAX_DIFFICULTY:
            failures.append(
                HalsteadViolation(name, "difficulty", difficulty, MAX_DIFFICULTY)
            )
        if bugs > MAX_BUGS:
            failures.append(HalsteadViolation(name, "estimated bugs", bugs, MAX_BUGS))

    return failures


def check_path(target: Path) -> list[HalsteadViolation]:
    """Return Halstead violations for a file or directory."""
    if target.is_dir():
        files = sorted(target.rglob("*.py"))
    elif target.is_file():
        files = [target]
    else:
        return [HalsteadViolation(str(target), "path not found", 1.0, 0.0)]

    failures: list[HalsteadViolation] = []
    for file_path in files:
        failures.extend(check_file(file_path))
    return failures


def format_violation(violation: HalsteadViolation) -> str:
    """Format a Halstead violation for CLI output."""
    return (
        f"  {violation.location} - {violation.metric} "
        f"{violation.actual:.1f} exceeds max {violation.maximum:.1f}"
    )
