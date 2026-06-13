"""Parsers that turn raw tool output into structured violations."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from kragg.models import Violation

_MYPY_LINE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+)(?::(?P<column>\d+))?:"
    r" (?P<severity>error|warning): (?P<message>.*?)"
    r"(?:\s+\[(?P<code>[a-z][a-z0-9-]*)\])?$"
)

_RADON_CC_BLOCK = re.compile(
    r"^\s+(?P<kind>[CFM]) (?P<line>\d+):\d+ (?P<name>\S+) - (?P<grade>[A-F])"
)

_RADON_MI_LINE = re.compile(r"^(?P<file>.+?) - (?P<grade>[A-C])(?: \(.*\))?$")

_PYTEST_FAILED = re.compile(r"^(?:FAILED|ERROR) (?P<id>\S+)")


def parse_ruff_json(stdout: str) -> tuple[Violation, ...]:
    """Parse `ruff check --output-format json` results."""
    try:
        data = cast(list[dict[str, Any]], json.loads(stdout))
    except json.JSONDecodeError:
        return ()
    violations: list[Violation] = []
    for item in data:
        location = item.get("location") or {}
        fixable = item.get("fix") is not None
        violations.append(
            Violation(
                message=str(item.get("message", "")),
                file=item.get("filename"),
                line=location.get("row"),
                column=location.get("column"),
                code=item.get("code"),
                fix_hint="auto-fixable: run `kragg fix`" if fixable else None,
            )
        )
    return tuple(violations)


def parse_mypy_output(stdout: str) -> tuple[Violation, ...]:
    """Parse mypy's default line-oriented output (errors and warnings)."""
    violations: list[Violation] = []
    for line in stdout.splitlines():
        match = _MYPY_LINE.match(line)
        if match is None:
            continue
        column = match.group("column")
        violations.append(
            Violation(
                message=match.group("message"),
                file=match.group("file"),
                line=int(match.group("line")),
                column=int(column) if column else None,
                code=match.group("code"),
            )
        )
    return tuple(violations)


def parse_radon_cc(stdout: str) -> tuple[Violation, ...]:
    """Parse `radon cc -s -n C` output (blocks graded C or worse)."""
    violations: list[Violation] = []
    current_file = ""
    for line in stdout.splitlines():
        if line and not line[0].isspace():
            current_file = line.strip()
            continue
        match = _RADON_CC_BLOCK.match(line)
        if match:
            violations.append(
                Violation(
                    message=(
                        f"{match.group('name')} has cyclomatic complexity grade "
                        f"{match.group('grade')} (max allowed: B)"
                    ),
                    file=current_file or None,
                    line=int(match.group("line")),
                    code=f"CC-{match.group('grade')}",
                    fix_hint="split into smaller functions or use early returns",
                )
            )
    return tuple(violations)


def parse_radon_mi(stdout: str) -> tuple[Violation, ...]:
    """Parse `radon mi -s` output, flagging files graded below A."""
    violations: list[Violation] = []
    for line in stdout.splitlines():
        match = _RADON_MI_LINE.match(line.rstrip())
        if match and match.group("grade") != "A":
            violations.append(
                Violation(
                    message=(
                        f"maintainability index grade {match.group('grade')} "
                        "(minimum: A)"
                    ),
                    file=match.group("file").strip(),
                    code=f"MI-{match.group('grade')}",
                )
            )
    return tuple(violations)


def parse_bandit_json(stdout: str) -> tuple[Violation, ...]:
    """Parse `bandit -f json` results."""
    try:
        data = cast(dict[str, Any], json.loads(stdout))
    except json.JSONDecodeError:
        return ()
    violations: list[Violation] = []
    for item in cast(list[dict[str, Any]], data.get("results", [])):
        severity = str(item.get("issue_severity", "")).lower()
        violations.append(
            Violation(
                message=f"{item.get('issue_text', '')} (severity: {severity})",
                file=item.get("filename"),
                line=item.get("line_number"),
                code=item.get("test_id"),
            )
        )
    return tuple(violations)


def parse_pip_audit_json(stdout: str) -> tuple[Violation, ...]:
    """Parse `pip-audit -f json` results into one violation per vulnerability."""
    try:
        data = cast(dict[str, Any], json.loads(stdout))
    except json.JSONDecodeError:
        return ()
    violations: list[Violation] = []
    for dep in cast(list[dict[str, Any]], data.get("dependencies", [])):
        name = dep.get("name", "unknown")
        version = dep.get("version", "?")
        for vuln in cast(list[dict[str, Any]], dep.get("vulns", [])):
            fixes = cast(list[str], vuln.get("fix_versions", []))
            fixed_in = ", ".join(fixes) if fixes else "no fix released"
            violations.append(
                Violation(
                    message=f"{name} {version} is vulnerable (fixed in: {fixed_in})",
                    code=vuln.get("id"),
                    fix_hint=(f"upgrade: uv pip install -U {name}" if fixes else None),
                )
            )
    return tuple(violations)


def parse_pytest_output(stdout: str) -> tuple[Violation, ...]:
    """Extract failed/errored test ids from pytest's short summary."""
    violations: list[Violation] = []
    for line in stdout.splitlines():
        match = _PYTEST_FAILED.match(line.strip())
        if match:
            test_id = match.group("id")
            file = test_id.split("::", 1)[0] if "::" in test_id else None
            violations.append(
                Violation(
                    message=line.strip(),
                    file=file,
                    fix_hint=f"re-run alone: uv run pytest {test_id}",
                )
            )
    return tuple(violations)
