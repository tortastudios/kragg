"""Gate pipeline engine: run gate specs, collecting structured results.

Fast gates (static analysis) all run so one invocation reveals every failure.
Slow gates (pytest, pip-audit) are skipped when fast gates fail, since their
results would be invalidated by the fixes anyway. The concrete pipelines are
assembled in `crag.catalog`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from crag.models import GateResult, Violation

FAST = "fast"
SLOW = "slow"

type OutputParser = Callable[[str], tuple[Violation, ...]]


@dataclass(frozen=True)
class GateSpec:
    """One gate in the pipeline: a name, a tier, and how to run it."""

    name: str
    tier: str
    runner: Callable[[], GateResult]
    skip_reason: str | None = None


def run_gates(
    specs: Sequence[GateSpec],
    fail_fast: bool = False,
    force_slow: bool = False,
) -> list[GateResult]:
    """Run gates, timing each; slow gates skip when fast gates failed."""
    results: list[GateResult] = []
    fast_failed = False
    halted = False
    for spec in specs:
        reason = _skip_reason(
            spec, fast_failed=fast_failed, halted=halted, force_slow=force_slow
        )
        if reason is not None:
            results.append(
                GateResult(
                    name=spec.name,
                    passed=False,
                    skipped=True,
                    skip_reason=reason,
                )
            )
            continue
        result = _timed(spec.runner)
        results.append(result)
        if not result.passed:
            fast_failed = fast_failed or spec.tier == FAST
            halted = halted or fail_fast
    return results


def _skip_reason(
    spec: GateSpec,
    fast_failed: bool,
    halted: bool,
    force_slow: bool,
) -> str | None:
    if halted:
        return "fail-fast"
    if spec.skip_reason is not None:
        return spec.skip_reason
    if spec.tier == SLOW and fast_failed and not force_slow:
        return "static gates failed"
    return None


def _timed(runner: Callable[[], GateResult]) -> GateResult:
    start = time.monotonic()
    result = runner()
    return replace(result, duration_ms=int((time.monotonic() - start) * 1000))
