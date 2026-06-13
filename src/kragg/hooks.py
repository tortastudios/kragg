"""Harness hook adapters.

`kragg hook claude` reads Claude Code's hook JSON from stdin, dispatches on
the event, and answers in the protocol the harness understands:

- PostToolUse: incremental check on the edited file; failures emit a
  ``{"decision": "block", "reason": ...}`` payload so violations re-enter
  the model's context immediately.
- Stop: full check; failures block the stop so "done" always means green.
  ``stop_hook_active`` is honored to prevent infinite stop loops.
- SessionStart: emits last-run status and critical functions as context.

Hooks fail open: any unexpected error exits 0 so a kragg bug never wedges
the harness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from kragg import journal, mapping, report
from kragg.catalog import build_check_gates
from kragg.changes import changed_python_files
from kragg.check import run_gates
from kragg.environment import resolve_project_environment
from kragg.policy import load_policy


def run_claude_hook(stdin_text: str, root: Path) -> int:
    """Handle one Claude Code hook invocation; never raises."""
    try:
        return _dispatch(stdin_text, root)
    except Exception:  # noqa: BLE001 - hooks must fail open.
        return 0


def _dispatch(stdin_text: str, root: Path) -> int:
    data = _parse_input(stdin_text)
    event = data.get("hook_event_name", "")
    if event == "Stop":
        return _stop(data, root)
    if event == "SessionStart":
        return _session_start(root)
    return _post_edit(data, root)


def _parse_input(stdin_text: str) -> dict[str, Any]:
    try:
        data = json.loads(stdin_text)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def _post_edit(data: dict[str, Any], root: Path) -> int:
    targets = _edit_targets(data, root)
    if not targets:
        return 0
    built = _run_check(root, targets, incremental=True)
    if built is None or built.passed:
        return 0
    _block(f"kragg gates failed:\n{report.render_text(built)}")
    return 0


def _stop(data: dict[str, Any], root: Path) -> int:
    if data.get("stop_hook_active"):
        return 0
    policy = load_policy(root)
    built = _run_check(root, (policy.source_paths[0],), incremental=False)
    if built is None or built.passed:
        return 0
    _block(f"kragg check must pass before finishing:\n{report.render_text(built)}")
    return 0


MAX_MAP_LINES = 60


def _session_start(root: Path) -> int:
    runs = journal.read_runs(root, 10)
    if runs:
        for line in journal.render_status_lines(runs):
            print(line)
    critical = _critical_functions(root)
    if critical:
        print("critical functions (extra scrutiny + tests when editing):")
        for name in critical:
            print(f"  {name}")
    _print_map_digest(root)
    return 0


def _print_map_digest(root: Path) -> None:
    lines = mapping.build_map(root, load_policy(root))
    if not lines:
        return
    print("project map (public symbols):")
    for line in lines[:MAX_MAP_LINES]:
        print(line)
    if len(lines) > MAX_MAP_LINES:
        print(f"  … {len(lines) - MAX_MAP_LINES} more — run `uv run kragg map`")


def _edit_targets(data: dict[str, Any], root: Path) -> tuple[str, ...]:
    tool_input = data.get("tool_input")
    file_path = ""
    if isinstance(tool_input, dict):
        file_path = str(cast(dict[str, Any], tool_input).get("file_path", ""))
    if file_path:
        if not file_path.endswith(".py"):
            return ()
        return (_relative(file_path, root),)
    policy = load_policy(root)
    allowed = (*policy.source_paths, *policy.test_paths)
    changed = changed_python_files(root, None, allowed)
    return tuple(changed) if changed else ()


def _run_check(
    root: Path,
    targets: tuple[str, ...],
    incremental: bool,
) -> report.CheckReport | None:
    policy = load_policy(root)
    env = resolve_project_environment(root)
    specs = build_check_gates(root, policy, env, targets, incremental=incremental)
    results = run_gates(specs)
    built = report.build_report(
        command="check",
        mode="changed" if incremental else "full",
        targets=targets,
        results=results,
        max_violations=policy.max_violations_per_gate,
        started_at=report.utc_now(),
        git_sha=report.git_sha(root),
    )
    journal.append_run(root, report.to_payload(built))
    return built


def _block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))


def _critical_functions(root: Path, limit: int = 8) -> list[str]:
    path = root / ".kragg" / "criticality.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    entries = cast(list[dict[str, Any]], data)
    return [
        str(entry.get("name"))
        for entry in entries
        if isinstance(entry, dict) and entry.get("is_critical")
    ][:limit]


def _relative(file_path: str, root: Path) -> str:
    path = Path(file_path)
    if path.is_absolute() and path.is_relative_to(root):
        return str(path.relative_to(root))
    return file_path
