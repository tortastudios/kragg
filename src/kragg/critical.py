"""Locate critical functions on disk.

Reads ``.kragg/criticality.json`` (written by ``kragg criticality --write``)
and resolves each critical function to its source file and the function key
used by coverage.py's JSON report. Public functions only by default (coverage
keys on the public function); ``include_private=True`` also returns private
critical functions, which mutation needs — it mutates whole modules, so a
HIGH-risk private boundary like ``Client._call`` must still select its file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from kragg.gates.criticality import module_name

type _ModuleFiles = dict[str, str]


@dataclass(frozen=True)
class CriticalFunction:
    """A critical function resolved to its location on disk."""

    qualname: str
    file: str
    fn_key: str
    fan_in: int


def critical_functions(
    root: Path,
    source_paths: tuple[str, ...],
    include_private: bool = False,
) -> tuple[CriticalFunction, ...]:
    """Resolve critical functions to a file and coverage key.

    Public only unless ``include_private`` is set (mutation passes it: the file,
    not the function, is the mutation unit, so private criticals must select).
    """
    entries = _critical_entries(root, include_private)
    if not entries:
        return ()
    module_files = _module_file_map(root, source_paths)
    resolved: list[CriticalFunction] = []
    for qualname, fan_in in entries:
        location = _resolve(qualname, module_files)
        if location is not None:
            file, fn_key = location
            resolved.append(CriticalFunction(qualname, file, fn_key, fan_in))
    return tuple(resolved)


def critical_files(
    root: Path,
    source_paths: tuple[str, ...],
    include_private: bool = False,
) -> tuple[str, ...]:
    """Return the distinct source files that define a critical function."""
    seen: list[str] = []
    for function in critical_functions(root, source_paths, include_private):
        if function.file not in seen:
            seen.append(function.file)
    return tuple(seen)


def _critical_entries(root: Path, include_private: bool) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    for item in _read_criticality(root):
        if not item.get("is_critical"):
            continue
        name = str(item.get("name", ""))
        if not name or (not include_private and _is_private(name)):
            continue
        entries.append((name, _as_int(item.get("fan_in"))))
    return entries


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _read_criticality(root: Path) -> list[dict[str, object]]:
    path = root / ".kragg" / "criticality.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _is_private(qualname: str) -> bool:
    return any(part.startswith("_") for part in qualname.split("."))


def _module_file_map(root: Path, source_paths: tuple[str, ...]) -> _ModuleFiles:
    module_files: _ModuleFiles = {}
    for source in source_paths:
        src_root = root / source
        if not src_root.is_dir():
            continue
        for path in sorted(src_root.rglob("*.py")):
            module_files[module_name(path, src_root)] = str(path.relative_to(root))
    return module_files


def _resolve(qualname: str, module_files: _ModuleFiles) -> tuple[str, str] | None:
    parts = qualname.split(".")
    for end in range(len(parts) - 1, 0, -1):
        module = ".".join(parts[:end])
        if module in module_files:
            return module_files[module], ".".join(parts[end:])
    return None
