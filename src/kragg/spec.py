"""Extract the test suite's spec: what each test claims to verify.

Test names and docstrings are the suite's narrative layer. Read mechanically,
they form a living contract — the describe/it tree that `rspec --format
documentation` prints. `kragg spec` renders it for the human reviewer; the
agent can read the test files directly, so this exists for the human.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

type _TestFunction = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class SpecItem:
    """One test rendered as a claim: a humanized name and optional docstring."""

    name: str
    doc: str | None


@dataclass(frozen=True)
class SpecFile:
    """The spec items extracted from one test file."""

    file: str
    items: tuple[SpecItem, ...]


def build_spec(root: Path, test_paths: tuple[str, ...]) -> tuple[SpecFile, ...]:
    """Extract a spec tree from every test file under the test paths."""
    files: list[SpecFile] = []
    for test_path in test_paths:
        test_root = root / test_path
        if not test_root.is_dir():
            continue
        for path in sorted(test_root.rglob("test_*.py")):
            items = _file_items(path)
            if items:
                files.append(SpecFile(str(path.relative_to(root)), items))
    return tuple(files)


def render_spec(files: tuple[SpecFile, ...]) -> list[str]:
    """Render the spec tree as readable documentation lines."""
    if not files:
        return ["no tests found"]
    total = sum(len(spec_file.items) for spec_file in files)
    lines = [f"spec: {total} tests across {len(files)} files"]
    for spec_file in files:
        lines.append(spec_file.file)
        lines.extend(_item_line(item) for item in spec_file.items)
    return lines


def _item_line(item: SpecItem) -> str:
    if item.doc:
        return f"  - {item.name}: {item.doc}"
    return f"  - {item.name}"


def _file_items(path: Path) -> tuple[SpecItem, ...]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return ()
    functions = [node for node in ast.walk(tree) if _is_test_function(node)]
    functions.sort(key=lambda node: node.lineno)
    return tuple(SpecItem(_humanize(node.name), _doc_line(node)) for node in functions)


def _is_test_function(node: ast.AST) -> TypeGuard[_TestFunction]:
    return (
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    )


def _humanize(name: str) -> str:
    return name.removeprefix("test_").replace("_", " ")


def _doc_line(node: _TestFunction) -> str | None:
    doc = ast.get_docstring(node)
    if not doc:
        return None
    return doc.strip().splitlines()[0]
