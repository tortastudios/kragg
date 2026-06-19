"""Read coverage.py's JSON report and surface gaps in critical functions.

``kragg check`` already runs pytest under coverage; this repurposes that data.
The percentage is the weak, gameable signal kragg deliberately demotes, so
this surfaces the *gap* instead — the uncovered lines of the functions that
matter most, ranked by fan-in, as file:line pointers an agent can act on. It
never reports a dashboard number.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from kragg.critical import CriticalFunction, critical_functions

COVERAGE_JSON_RELATIVE = ".kragg/coverage.json"

type _JsonObject = dict[str, object]


@dataclass(frozen=True)
class FunctionCoverage:
    """Coverage outcome for one public critical function."""

    qualname: str
    file: str
    fan_in: int
    missing_lines: tuple[int, ...]
    measured: bool


def coverage_path(root: Path) -> Path:
    return root / COVERAGE_JSON_RELATIVE


def read_report(root: Path) -> _JsonObject | None:
    """Read the last run's coverage JSON; None when missing or invalid."""
    try:
        data = json.loads(coverage_path(root).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def critical_gaps(
    root: Path,
    source_paths: tuple[str, ...],
) -> tuple[FunctionCoverage, ...]:
    """Uncovered lines per public critical function, ranked by fan-in."""
    report = read_report(root)
    if report is None:
        return ()
    files = _normalized_files(report, root)
    rows = [
        _function_coverage(fn, files) for fn in critical_functions(root, source_paths)
    ]
    return tuple(sorted(rows, key=lambda row: row.fan_in, reverse=True))


@dataclass(frozen=True)
class _Partition:
    with_gaps: list[FunctionCoverage]
    clean: list[FunctionCoverage]
    unmeasured: list[FunctionCoverage]


def render_gaps(gaps: tuple[FunctionCoverage, ...]) -> list[str]:
    """Render criticality-ranked coverage gaps as token-efficient lines."""
    if not gaps:
        return ["no critical functions (run `kragg criticality --write`)"]
    parts = _partition(gaps)
    lines = [
        f"critical coverage: {len(gaps)} functions, "
        f"{len(parts.with_gaps)} with gaps, {len(parts.clean)} clean, "
        f"{len(parts.unmeasured)} unmeasured"
    ]
    lines.extend(_gap_line(row) for row in parts.with_gaps)
    lines.extend(_unmeasured_line(row) for row in parts.unmeasured)
    return lines


def _partition(gaps: tuple[FunctionCoverage, ...]) -> _Partition:
    with_gaps: list[FunctionCoverage] = []
    clean: list[FunctionCoverage] = []
    unmeasured: list[FunctionCoverage] = []
    for row in gaps:
        if not row.measured:
            unmeasured.append(row)
        elif row.missing_lines:
            with_gaps.append(row)
        else:
            clean.append(row)
    return _Partition(with_gaps, clean, unmeasured)


def _gap_line(row: FunctionCoverage) -> str:
    return (
        f"  {row.file} {row.qualname} (fan-in {row.fan_in}) "
        f"— uncovered: {_format_lines(row.missing_lines)}"
    )


def _unmeasured_line(row: FunctionCoverage) -> str:
    return f"  {row.file} {row.qualname} (fan-in {row.fan_in}) — no test imports it"


def _format_lines(lines: tuple[int, ...], cap: int = 12) -> str:
    shown = ", ".join(str(line) for line in lines[:cap])
    if len(lines) > cap:
        return f"{shown}, +{len(lines) - cap} more"
    return shown


def _normalized_files(report: _JsonObject, root: Path) -> _JsonObject:
    files = report.get("files")
    if not isinstance(files, dict):
        return {}
    normalized: _JsonObject = {}
    for key, entry in files.items():
        normalized[_relative_key(str(key), root)] = entry
    return normalized


def _relative_key(key: str, root: Path) -> str:
    path = Path(key)
    if path.is_absolute() and path.is_relative_to(root):
        return str(path.relative_to(root))
    return key


def _function_coverage(
    fn: CriticalFunction,
    files: _JsonObject,
) -> FunctionCoverage:
    entry = _function_entry(files, fn.file, fn.fn_key)
    if entry is None:
        return FunctionCoverage(fn.qualname, fn.file, fn.fan_in, (), measured=False)
    missing = _int_tuple(entry.get("missing_lines"))
    return FunctionCoverage(fn.qualname, fn.file, fn.fan_in, missing, measured=True)


def _function_entry(
    files: _JsonObject,
    file: str,
    fn_key: str,
) -> _JsonObject | None:
    file_entry = files.get(file)
    if not isinstance(file_entry, dict):
        return None
    functions = file_entry.get("functions")
    if not isinstance(functions, dict):
        return None
    entry = functions.get(fn_key)
    return entry if isinstance(entry, dict) else None


def _int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int))
