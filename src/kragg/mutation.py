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

import ast
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
BASELINE_RELATIVE = ".kragg/mutants.baseline"

type _Span = tuple[int, int, int, int]


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
    column: int
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
    line, column = _start_position(mutation.get("start_pos"))
    return Survivor(
        file=str(mutation.get("module_path", "")),
        line=line,
        column=column,
        function=str(mutation.get("definition_name", "")),
        operator=str(mutation.get("operator_name", "")),
        occurrence=_as_int(mutation.get("occurrence")),
        diff=str(work_result.get("diff", "")),
    )


def _start_position(start: object) -> tuple[int, int]:
    if isinstance(start, list) and len(start) >= 2:
        line = start[0] if isinstance(start[0], int) else 0
        column = start[1] if isinstance(start[1], int) else 0
        return line, column
    return 0, 0


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
    # cosmic-ray init refuses to overwrite a session that already has results,
    # so each run starts from a fresh session over the current code.
    session_path.unlink(missing_ok=True)
    for step in ("init", "exec"):
        result = _cosmic_ray(env, root, step, str(config_path), str(session_path))
        if not result.passed:
            raise MutationError(
                f"cosmic-ray {step} failed for {target}: {result.output}"
            )
    dump = _cosmic_ray(env, root, "dump", str(session_path))
    survivors = drop_annotation_mutants(parse_survivors(dump.stdout), root / target)
    return list(survivors)


def drop_annotation_mutants(
    survivors: tuple[Survivor, ...],
    path: Path,
) -> tuple[Survivor, ...]:
    """Drop survivors that fall inside a type annotation.

    Under ``from __future__ import annotations`` annotations are strings and
    never evaluated, so mutating an operator inside one (``str | None`` ->
    ``str & None``) has no runtime effect and can never be killed — it only
    ever survives. Dropping those removes a large class of equivalent mutants.
    """
    spans = _annotation_spans(path)
    if not spans:
        return survivors
    return tuple(s for s in survivors if not _within_any(s.line, s.column, spans))


def _annotation_spans(path: Path) -> list[_Span]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except (OSError, SyntaxError):
        return []
    spans: list[_Span] = []
    for node in ast.walk(tree):
        annotation = _annotation_of(node)
        if annotation is not None and annotation.end_lineno is not None:
            spans.append(
                (
                    annotation.lineno,
                    annotation.col_offset,
                    annotation.end_lineno,
                    annotation.end_col_offset or 0,
                )
            )
    return spans


def _annotation_of(node: ast.AST) -> ast.expr | None:
    if isinstance(node, ast.arg):
        return node.annotation
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return node.returns
    if isinstance(node, ast.AnnAssign):
        return node.annotation
    if isinstance(node, ast.TypeAlias):
        return node.value  # PEP 695 `type X = ...` is lazily evaluated too
    return None


def _within_any(line: int, column: int, spans: list[_Span]) -> bool:
    return any(_within(line, column, span) for span in spans)


def _within(line: int, column: int, span: _Span) -> bool:
    start_line, start_col, end_line, end_col = span
    if not start_line <= line <= end_line:
        return False
    if line == start_line and column < start_col:
        return False
    if line == end_line and column > end_col:
        return False
    return True


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


def baseline_path(root: Path) -> Path:
    return root / BASELINE_RELATIVE


def load_baseline(root: Path) -> set[str]:
    """Read accepted (e.g. equivalent) mutant signatures; empty when absent."""
    try:
        data = json.loads(baseline_path(root).read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item) for item in data}


def write_baseline(root: Path, survivors: tuple[Survivor, ...]) -> int:
    """Record the survivors' signatures as the accepted baseline."""
    signatures = sorted({survivor.signature() for survivor in survivors})
    path = baseline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(signatures, indent=1) + "\n")
    return len(signatures)


def filter_baselined(
    survivors: tuple[Survivor, ...],
    baseline: set[str],
) -> tuple[Survivor, ...]:
    """Drop survivors whose signature is in the accepted baseline."""
    return tuple(s for s in survivors if s.signature() not in baseline)
