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

from kragg.critical import critical_functions

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


@dataclass(frozen=True)
class PropertyCoverage:
    """Whether a public critical function has any property-based test."""

    qualname: str
    fan_in: int
    has_property_test: bool


def property_coverage(
    root: Path,
    source_paths: tuple[str, ...],
    test_paths: tuple[str, ...],
) -> tuple[PropertyCoverage, ...]:
    """Which public critical functions a Hypothesis test exercises, by fan-in."""
    corpus = _property_test_corpus(root, test_paths)
    rows = [
        PropertyCoverage(fn.qualname, fn.fan_in, _simple_name(fn.qualname) in corpus)
        for fn in critical_functions(root, source_paths)
    ]
    return tuple(sorted(rows, key=lambda row: row.fan_in, reverse=True))


def render_property_coverage(rows: tuple[PropertyCoverage, ...]) -> list[str]:
    """Render property-based coverage of critical functions (informational)."""
    if not rows:
        return []
    covered = sum(1 for row in rows if row.has_property_test)
    lines = [
        f"property-based coverage: {covered}/{len(rows)} critical functions "
        "(property tests kill more mutants than example tests)"
    ]
    for row in rows:
        if not row.has_property_test:
            lines.append(f"  {row.qualname} (fan-in {row.fan_in}) — only example-based")
    return lines


def _simple_name(qualname: str) -> str:
    return qualname.rsplit(".", 1)[-1]


def _property_test_corpus(root: Path, test_paths: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for test_path in test_paths:
        test_root = root / test_path
        if not test_root.is_dir():
            continue
        for path in sorted(test_root.rglob("test_*.py")):
            chunks.extend(_property_chunks(path))
    return "\n".join(chunks)


def _property_chunks(path: Path) -> list[str]:
    source = path.read_text()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    chunks: list[str] = []
    for node in ast.walk(tree):
        if _is_property_test(node):
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                chunks.append(segment)
    return chunks


def _is_property_test(node: ast.AST) -> bool:
    if not _is_test_function(node):
        return False
    return any(_decorator_name(dec) == "given" for dec in node.decorator_list)


def _decorator_name(decorator: ast.expr) -> str:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""
