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
from pathlib import Path

from kragg.changes import changed_python_files
from kragg.critical import critical_files
from kragg.policy import KraggPolicy

DEFAULT_TIMEOUT = 30.0


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
