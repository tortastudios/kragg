"""Gate: critical functions must not change without test changes.

Reads `.crag/criticality.json` (written by `crag criticality --write`) and
the git working-tree change set. If a changed source file defines a public
critical function and no test file changed alongside it, the gate fails.
Private symbols are exempt; outside a git repository the gate passes.
"""

from __future__ import annotations

import json
from pathlib import Path

from crag.changes import changed_python_files
from crag.gates.criticality import module_name
from crag.models import Violation


def check_critical_tests(
    root: Path,
    source_paths: tuple[str, ...],
    test_paths: tuple[str, ...],
) -> tuple[Violation, ...]:
    """Return violations for critical functions changed without tests."""
    changed = changed_python_files(root, None, (*source_paths, *test_paths))
    if not changed:
        return ()
    if any(_under_any(name, test_paths) for name in changed):
        return ()
    critical = _critical_entries(root)
    if not critical:
        return ()
    module_files = _module_file_map(root, source_paths)
    changed_set = set(changed)
    violations: list[Violation] = []
    for qualname, fan_in in critical:
        file = _file_for_qualname(qualname, module_files)
        if file is not None and file in changed_set:
            violations.append(
                Violation(
                    message=(
                        f"critical function {qualname} (fan-in {fan_in}) "
                        "changed without test changes"
                    ),
                    file=file,
                    code="critical-tests",
                    fix_hint=(
                        "add or update a test covering "
                        f"{qualname.rsplit('.', 1)[-1]}, or revert the change"
                    ),
                )
            )
    return tuple(violations)


def _critical_entries(root: Path) -> list[tuple[str, int]]:
    path = root / ".crag" / "criticality.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    entries: list[tuple[str, int]] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("is_critical"):
            continue
        name = str(item.get("name", ""))
        if name and not _is_private(name):
            entries.append((name, int(item.get("fan_in", 0))))
    return entries


def _is_private(qualname: str) -> bool:
    return any(part.startswith("_") for part in qualname.split("."))


def _module_file_map(
    root: Path,
    source_paths: tuple[str, ...],
) -> dict[str, str]:
    module_files: dict[str, str] = {}
    for source in source_paths:
        src_root = root / source
        if not src_root.is_dir():
            continue
        for path in sorted(src_root.rglob("*.py")):
            module_files[module_name(path, src_root)] = str(path.relative_to(root))
    return module_files


def _file_for_qualname(
    qualname: str,
    module_files: dict[str, str],
) -> str | None:
    parts = qualname.split(".")
    for end in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in module_files:
            return module_files[candidate]
    return None


def _under_any(name: str, prefixes: tuple[str, ...]) -> bool:
    path = Path(name)
    return any(
        path == Path(prefix) or path.is_relative_to(prefix) for prefix in prefixes
    )
