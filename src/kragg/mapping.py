"""Project map: a token-cheap inventory of public symbols.

Agents reinvent what they cannot see. The map lists every public function,
class, and method with its first docstring line and criticality flag, so a
session can discover existing code for a few hundred tokens instead of
re-reading the tree.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from kragg.gates.criticality import module_name
from kragg.policy import KraggPolicy

MAX_DOC_CHARS = 60

type _Documented = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def build_map(root: Path, policy: KraggPolicy) -> list[str]:
    """Return map lines: one per module, indented public symbols beneath."""
    flags = _criticality_flags(root)
    lines: list[str] = []
    for source in policy.source_paths:
        src_root = root / source
        if not src_root.is_dir():
            continue
        for path in sorted(src_root.rglob("*.py")):
            module = module_name(path, src_root)
            entries = _module_entries(path, module, flags)
            if entries:
                lines.append(module)
                lines.extend(entries)
    return lines


def write_map(lines: list[str], output_path: Path) -> None:
    """Write the map for hooks and agents to read."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")


def _module_entries(
    path: Path,
    module: str,
    flags: dict[str, str],
) -> list[str]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return []
    entries: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("_"):
                entries.append(_function_entry(node, f"{module}.{node.name}", flags))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            entries.append(_class_entry(node, module, flags))
            entries.extend(_method_entries(node, module, flags))
    return entries


def _function_entry(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    qualname: str,
    flags: dict[str, str],
    prefix: str = "",
) -> str:
    args = ", ".join(arg.arg for arg in node.args.args if arg.arg != "self")
    return (
        f"  {prefix}{node.name}({args})"
        f"{_doc_suffix(node)}{_risk_suffix(qualname, flags)}"
    )


def _class_entry(node: ast.ClassDef, module: str, flags: dict[str, str]) -> str:
    qualname = f"{module}.{node.name}"
    return f"  class {node.name}{_doc_suffix(node)}{_risk_suffix(qualname, flags)}"


def _method_entries(
    node: ast.ClassDef,
    module: str,
    flags: dict[str, str],
) -> list[str]:
    entries: list[str] = []
    for child in node.body:
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            if not child.name.startswith("_"):
                qualname = f"{module}.{node.name}.{child.name}"
                entries.append(
                    _function_entry(child, qualname, flags, prefix=f"{node.name}.")
                )
    return entries


def _doc_suffix(node: _Documented) -> str:
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    first = doc.strip().splitlines()[0]
    if len(first) > MAX_DOC_CHARS:
        first = first[: MAX_DOC_CHARS - 1] + "…"
    return f" — {first}"


def _risk_suffix(qualname: str, flags: dict[str, str]) -> str:
    risk = flags.get(qualname)
    return f"  [{risk}]" if risk else ""


def _criticality_flags(root: Path) -> dict[str, str]:
    path = root / ".kragg" / "criticality.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}
    flags: dict[str, str] = {}
    for entry in data:
        if isinstance(entry, dict) and entry.get("is_critical"):
            flags[str(entry.get("name"))] = str(entry.get("risk", "MED"))
    return flags
