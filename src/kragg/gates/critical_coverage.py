"""Gate: public critical functions must have no uncovered lines.

Reads ``.kragg/coverage.json`` (written by the pytest gate) and flags any
public critical function with missing lines. Coverage percentage is gameable,
so kragg does not gate on it globally; instead it applies the strictest bar —
full coverage — only where it matters most: the highest-fan-in functions.
Functions coverage never observed executing are surfaced by ``kragg coverage``
but not failed here, to keep the gate free of measurement-key false positives.
"""

from __future__ import annotations

from pathlib import Path

from kragg.coverage import FunctionCoverage, critical_gaps
from kragg.models import Violation


def check_critical_coverage(
    root: Path,
    source_paths: tuple[str, ...],
) -> tuple[Violation, ...]:
    """Return violations for critical functions with uncovered lines."""
    violations: list[Violation] = []
    for gap in critical_gaps(root, source_paths):
        if gap.measured and gap.missing_lines:
            violations.append(_violation(gap))
    return tuple(violations)


def _violation(gap: FunctionCoverage) -> Violation:
    simple = gap.qualname.rsplit(".", 1)[-1]
    preview = ", ".join(str(line) for line in gap.missing_lines[:6])
    return Violation(
        message=(
            f"critical function {gap.qualname} has "
            f"{len(gap.missing_lines)} uncovered lines"
        ),
        file=gap.file,
        line=gap.missing_lines[0],
        code="critical-coverage",
        fix_hint=f"add a test exercising {simple} (uncovered: {preview})",
    )
