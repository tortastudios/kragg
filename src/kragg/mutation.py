"""Targeted mutation testing via cosmic-ray.

Mutation testing is the rigorous form of kragg's founding claim: coverage
proves a line ran, mutation proves a test would *notice* if that line broke.
The cost that sinks generic mutation tools is that they mutate everything;
kragg has a criticality call-graph and a git diff, so it mutates only the
changed files that define a critical function — usually a handful, not the
whole tree.

This module is the planning half — selecting targets and generating cosmic-ray
config. The runner half (same module, below) executes cosmic-ray and turns
surviving mutants into violations.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

from kragg.changes import changed_python_files
from kragg.critical import critical_files
from kragg.environment import ProjectEnvironment
from kragg.models import CompletedCommand, Violation
from kragg.policy import KraggPolicy
from kragg.runner import run_command

DEFAULT_TIMEOUT = 30.0


class MutationError(RuntimeError):
    """cosmic-ray could not complete a mutation session."""


def select_targets(
    root: Path,
    policy: KraggPolicy,
    since: str | None,
    mutate_all: bool,
) -> tuple[str, ...] | None:
    """Source files to mutate: critical files, narrowed to the change set.

    Returns None when the change set cannot be computed (not a git repository)
    and ``mutate_all`` is False, so the caller can ask for ``--all`` instead.
    """
    criticals = critical_files(root, policy.source_paths)
    if mutate_all:
        return criticals
    changed = changed_python_files(root, since, policy.source_paths)
    if changed is None:
        return None
    changed_set = set(changed)
    return tuple(path for path in criticals if path in changed_set)


def format_test_command(
    python_cmd: tuple[str, ...],
    test_paths: tuple[str, ...],
) -> str:
    """Build the per-mutant test command, stopping at the first failure."""
    return shlex.join([*python_cmd, "-m", "pytest", "-x", "-q", *test_paths])


def build_config(
    module_path: str,
    test_command: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Render a cosmic-ray TOML config for one module under test.

    String values go through ``json.dumps``: TOML basic strings share JSON's
    quoting and escape rules, so this is correct for paths with spaces.
    """
    return "\n".join(
        [
            "[cosmic-ray]",
            f"module-path = {json.dumps(module_path)}",
            f"timeout = {timeout}",
            "excluded-modules = []",
            f"test-command = {json.dumps(test_command)}",
            "",
            "[cosmic-ray.distributor]",
            'name = "local"',
            "",
        ]
    )


@dataclass(frozen=True)
class Survivor:
    """A mutant the test suite failed to kill."""

    file: str
    line: int
    function: str
    operator: str
    occurrence: int
    diff: str

    def signature(self) -> str:
        """A stable identity for baselining, independent of the session id."""
        return f"{self.file}::{self.operator}::{self.occurrence}"


@dataclass(frozen=True)
class MutationReport:
    """Outcome of a mutation run across the targeted files."""

    survivors: tuple[Survivor, ...]
    files_tested: int
    error: str | None = None


def parse_survivors(dump: str) -> tuple[Survivor, ...]:
    """Parse `cosmic-ray dump` JSONL, keeping only surviving mutants."""
    survivors: list[Survivor] = []
    for line in dump.splitlines():
        survivor = _parse_dump_line(line.strip())
        if survivor is not None:
            survivors.append(survivor)
    return tuple(survivors)


def _parse_dump_line(line: str) -> Survivor | None:
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, list) or len(record) != 2:
        return None
    work_item, work_result = record
    if not _is_survivor(work_result):
        return None
    return _survivor_from(work_item, work_result)


def _is_survivor(work_result: object) -> bool:
    return (
        isinstance(work_result, dict)
        and work_result.get("test_outcome") == "survived"
    )


def _survivor_from(
    work_item: object,
    work_result: dict[str, object],
) -> Survivor | None:
    mutation = _first_mutation(work_item)
    if mutation is None:
        return None
    start = mutation.get("start_pos")
    line = start[0] if isinstance(start, list) and start else 0
    return Survivor(
        file=str(mutation.get("module_path", "")),
        line=line if isinstance(line, int) else 0,
        function=str(mutation.get("definition_name", "")),
        operator=str(mutation.get("operator_name", "")),
        occurrence=_as_int(mutation.get("occurrence")),
        diff=str(work_result.get("diff", "")),
    )


def _first_mutation(work_item: object) -> dict[str, object] | None:
    if not isinstance(work_item, dict):
        return None
    mutations = work_item.get("mutations")
    if not isinstance(mutations, list) or not mutations:
        return None
    return mutations[0] if isinstance(mutations[0], dict) else None


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def cosmic_ray_available(env: ProjectEnvironment) -> bool:
    """Whether cosmic-ray's console script is present in the project env."""
    if env.python is not None:
        return (env.python.parent / "cosmic-ray").exists()
    return True


def run_mutation(
    root: Path,
    env: ProjectEnvironment,
    policy: KraggPolicy,
    targets: tuple[str, ...],
) -> MutationReport:
    """Mutate each target file with cosmic-ray and collect survivors."""
    artifact_dir = root / ".kragg" / "mutation"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    test_command = format_test_command(tuple(env.command()), policy.test_paths)
    survivors: list[Survivor] = []
    try:
        for target in targets:
            found = _mutate_file(root, env, artifact_dir, target, test_command)
            survivors.extend(found)
    except (MutationError, OSError) as exc:
        return MutationReport(tuple(survivors), 0, str(exc))
    return MutationReport(tuple(survivors), len(targets))


def _mutate_file(
    root: Path,
    env: ProjectEnvironment,
    artifact_dir: Path,
    target: str,
    test_command: str,
) -> list[Survivor]:
    stem = target.replace("/", "_").replace(".", "_")
    config_path = artifact_dir / f"{stem}.toml"
    session_path = artifact_dir / f"{stem}.sqlite"
    config_path.write_text(build_config(target, test_command))
    for step in ("init", "exec"):
        result = _cosmic_ray(env, root, step, str(config_path), str(session_path))
        if not result.passed:
            raise MutationError(
                f"cosmic-ray {step} failed for {target}: {result.output}"
            )
    dump = _cosmic_ray(env, root, "dump", str(session_path))
    return list(parse_survivors(dump.stdout))


def _cosmic_ray(
    env: ProjectEnvironment,
    root: Path,
    *args: str,
) -> CompletedCommand:
    command = env.script_command("cosmic-ray", *args)
    return run_command(f"cosmic-ray {args[0]}", command, root)


def survivor_violation(survivor: Survivor) -> Violation:
    """Render a survivor as a violation with an actionable fix hint."""
    change = diff_summary(survivor.diff)
    detail = f" — {change}" if change else f" ({_short_operator(survivor.operator)})"
    return Violation(
        message=f"surviving mutant in {survivor.function}{detail}",
        file=survivor.file,
        line=survivor.line,
        code="mutant",
        fix_hint=f"add a test that fails when {survivor.function} is mutated here",
    )


def render_survivors(survivors: tuple[Survivor, ...]) -> list[str]:
    """Render survivors as token-efficient file:line lines."""
    if not survivors:
        return ["no surviving mutants"]
    files = len({survivor.file for survivor in survivors})
    header = f"mutation: {len(survivors)} surviving mutants in {files} files"
    lines = [header]
    for survivor in survivors:
        violation = survivor_violation(survivor)
        lines.append(f"  {violation.location()} {violation.message}")
    return lines


def diff_summary(diff: str) -> str:
    """Summarize a mutation diff as `old -> new` from its first changed lines."""
    removed = _first_change(diff, "-", "---")
    added = _first_change(diff, "+", "+++")
    if removed and added:
        return f"{removed} -> {added}"
    return ""


def _first_change(diff: str, prefix: str, skip: str) -> str:
    for line in diff.splitlines():
        if line.startswith(prefix) and not line.startswith(skip):
            return line[len(prefix):].strip()
    return ""


def _short_operator(operator: str) -> str:
    return operator.rsplit("/", 1)[-1]
