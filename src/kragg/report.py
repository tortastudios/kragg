"""Consolidated check reports: dedupe, caps, JSON schema, text rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib import metadata
from typing import TypedDict

from kragg.models import GateResult, Violation

SCHEMA_VERSION = 1

EXIT_OK = 0
EXIT_GATE_FAILURES = 1
EXIT_USAGE = 2
EXIT_ENVIRONMENT = 3

MAX_RAW_LINES = 40
MAX_RAW_CHARS = 4000
MAX_DEDUPE_LOCATIONS = 5


class ViolationPayload(TypedDict):
    file: str | None
    line: int | None
    column: int | None
    code: str | None
    message: str
    fix_hint: str | None


class GatePayload(TypedDict):
    name: str
    passed: bool
    skipped: bool
    skip_reason: str | None
    error: bool
    duration_ms: int
    violation_count: int
    violations: list[ViolationPayload]
    truncated: bool
    raw_output: str | None


class SummaryPayload(TypedDict):
    gates_total: int
    gates_passed: int
    gates_failed: int
    gates_skipped: int
    violations_total: int
    violations_shown: int


class ReportPayload(TypedDict):
    schema_version: int
    kragg_version: str
    command: str
    mode: str
    targets: list[str]
    git_sha: str | None
    started_at: str
    duration_ms: int
    passed: bool
    exit_code: int
    summary: SummaryPayload
    gates: list[GatePayload]
    next_actions: list[str]


@dataclass(frozen=True)
class ProcessedGate:
    """A gate result with display violations deduped and capped."""

    result: GateResult
    shown: tuple[Violation, ...]
    truncated: bool
    raw_output: str | None


@dataclass(frozen=True)
class CheckReport:
    """A full pipeline run, ready to render as text or JSON."""

    command: str
    mode: str
    targets: tuple[str, ...]
    gates: tuple[ProcessedGate, ...]
    started_at: str
    git_sha: str | None

    @property
    def passed(self) -> bool:
        return all(g.result.passed or g.result.skipped for g in self.gates)

    @property
    def exit_code(self) -> int:
        if any(g.result.error for g in self.gates):
            return EXIT_ENVIRONMENT
        if not self.passed:
            return EXIT_GATE_FAILURES
        return EXIT_OK

    @property
    def duration_ms(self) -> int:
        return sum(g.result.duration_ms for g in self.gates)


def build_report(
    command: str,
    mode: str,
    targets: tuple[str, ...],
    results: list[GateResult],
    max_violations: int,
    started_at: str,
    git_sha: str | None,
) -> CheckReport:
    """Process raw gate results into a renderable report."""
    return CheckReport(
        command=command,
        mode=mode,
        targets=targets,
        gates=tuple(_process_gate(r, max_violations) for r in results),
        started_at=started_at,
        git_sha=git_sha,
    )


def _process_gate(result: GateResult, max_violations: int) -> ProcessedGate:
    deduped = dedupe_violations(result.violations)
    shown = deduped[:max_violations]
    raw_output: str | None = None
    failed = not result.passed and not result.skipped
    if failed and not shown and result.output:
        raw_output = cap_output(result.output)
    return ProcessedGate(
        result=result,
        shown=shown,
        truncated=len(shown) < len(deduped),
        raw_output=raw_output,
    )


type _ViolationGroups = dict[tuple[str | None, str], list[Violation]]


def dedupe_violations(violations: tuple[Violation, ...]) -> tuple[Violation, ...]:
    """Collapse identical (code, message) findings spanning many locations."""
    groups: _ViolationGroups = {}
    for violation in violations:
        groups.setdefault((violation.code, violation.message), []).append(violation)

    deduped: list[Violation] = []
    for group in groups.values():
        first = group[0]
        if len(group) == 1:
            deduped.append(first)
            continue
        locations = [v.location() for v in group[1:] if v.location()]
        locations = locations[:MAX_DEDUPE_LOCATIONS]
        where = f" at {', '.join(locations)}" if locations else ""
        deduped.append(
            replace(first, message=f"{first.message} (+{len(group) - 1} more{where})")
        )
    return tuple(deduped)


def cap_output(output: str) -> str:
    """Keep the tail of long raw output (summaries live at the end)."""
    lines = output.splitlines()
    if len(lines) > MAX_RAW_LINES:
        kept = lines[-MAX_RAW_LINES:]
        lines = [f"... [truncated, {len(output.splitlines())} lines total]", *kept]
    capped = "\n".join(lines)
    if len(capped) > MAX_RAW_CHARS:
        capped = f"... [truncated]\n{capped[-MAX_RAW_CHARS:]}"
    return capped


def to_payload(report: CheckReport) -> ReportPayload:
    """Serialize a report to the stable JSON schema."""
    gates = [_gate_payload(gate) for gate in report.gates]
    return ReportPayload(
        schema_version=SCHEMA_VERSION,
        kragg_version=kragg_version(),
        command=report.command,
        mode=report.mode,
        targets=list(report.targets),
        git_sha=report.git_sha,
        started_at=report.started_at,
        duration_ms=report.duration_ms,
        passed=report.passed,
        exit_code=report.exit_code,
        summary=_summary_payload(report),
        gates=gates,
        next_actions=next_actions(report),
    )


def _gate_payload(gate: ProcessedGate) -> GatePayload:
    result = gate.result
    return GatePayload(
        name=result.name,
        passed=result.passed,
        skipped=result.skipped,
        skip_reason=result.skip_reason,
        error=result.error,
        duration_ms=result.duration_ms,
        violation_count=result.violation_count,
        violations=[_violation_payload(v) for v in gate.shown],
        truncated=gate.truncated,
        raw_output=gate.raw_output,
    )


def _violation_payload(violation: Violation) -> ViolationPayload:
    return ViolationPayload(
        file=violation.file,
        line=violation.line,
        column=violation.column,
        code=violation.code,
        message=violation.message,
        fix_hint=violation.fix_hint,
    )


def _summary_payload(report: CheckReport) -> SummaryPayload:
    results = [g.result for g in report.gates]
    skipped = sum(1 for r in results if r.skipped)
    passed = sum(1 for r in results if r.passed and not r.skipped)
    return SummaryPayload(
        gates_total=len(results),
        gates_passed=passed,
        gates_failed=len(results) - passed - skipped,
        gates_skipped=skipped,
        violations_total=sum(r.violation_count for r in results),
        violations_shown=sum(len(g.shown) for g in report.gates),
    )


def next_actions(report: CheckReport) -> list[str]:
    """Tell the agent what to do next, in priority order."""
    actions = _environment_fixes(report)
    fixable = _auto_fixable_count(report)
    if fixable:
        actions.append(f"run `kragg fix` to auto-fix {fixable} ruff violations")
    if not report.passed and not actions:
        actions.append(
            "fix the violations at the file:line locations above, "
            f"then re-run `kragg {report.command}`"
        )
    return actions


def _environment_fixes(report: CheckReport) -> list[str]:
    actions: list[str] = []
    for gate in report.gates:
        if gate.result.error and gate.raw_output:
            fixes = [
                line for line in gate.raw_output.splitlines() if line.startswith("Fix:")
            ]
            actions.extend(f"{gate.result.name}: {fix}" for fix in fixes)
    return actions


def _auto_fixable_count(report: CheckReport) -> int:
    return sum(
        1
        for gate in report.gates
        for violation in gate.shown
        if violation.fix_hint is not None
        and violation.fix_hint.startswith("auto-fixable")
    )


def render_json(report: CheckReport) -> str:
    return json.dumps(to_payload(report), indent=1)


def render_text(report: CheckReport) -> str:
    lines: list[str] = []
    for gate in report.gates:
        lines.extend(_render_gate_text(gate))
    summary = _summary_payload(report)
    lines.append(
        f"{summary['gates_passed']} passed, {summary['gates_failed']} failed, "
        f"{summary['gates_skipped']} skipped"
    )
    lines.extend(f"next: {action}" for action in next_actions(report))
    return "\n".join(lines)


def _render_gate_text(gate: ProcessedGate) -> list[str]:
    result = gate.result
    seconds = result.duration_ms / 1000
    if result.skipped:
        return [f"[SKIP] {result.name} — {result.skip_reason}"]
    if result.passed:
        return [f"[PASS] {result.name} ({seconds:.1f}s)"]
    label = "ERROR" if result.error else "FAIL"
    count = f" — {result.violation_count} violations" if result.violation_count else ""
    lines = [f"[{label}] {result.name} ({seconds:.1f}s){count}"]
    for violation in gate.shown:
        lines.append(f"  {_render_violation_text(violation)}")
    if gate.truncated:
        hidden = result.violation_count - len(gate.shown)
        lines.append(f"  ... {hidden} more not shown (use --max-violations)")
    if gate.raw_output:
        lines.extend(f"  {line}" for line in gate.raw_output.splitlines())
    return lines


def _render_violation_text(violation: Violation) -> str:
    parts: list[str] = []
    location = violation.location()
    if location:
        parts.append(location)
    if violation.code:
        parts.append(violation.code)
    parts.append(violation.message)
    text = " ".join(parts)
    if violation.fix_hint:
        text = f"{text} -> {violation.fix_hint}"
    return text


def kragg_version() -> str:
    try:
        return metadata.version("kragg")
    except metadata.PackageNotFoundError:
        return "unknown"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
