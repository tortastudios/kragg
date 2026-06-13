"""Test-quality gate: coverage is gameable, assertions are not.

Two checks:

- every ``test_*`` function must contain at least one assertion
  (``assert``, ``pytest.raises``, or an ``assert_*`` method call)
- every public critical function (from ``.kragg/criticality.json``) must be
  referenced by name somewhere in the test suite
"""

from __future__ import annotations

import ast
from pathlib import Path

from kragg.gates.criticality import read_json
from kragg.models import Violation

type _TestFunction = ast.FunctionDef | ast.AsyncFunctionDef


def check_tests(
    root: Path,
    test_paths: tuple[str, ...],
) -> tuple[Violation, ...]:
    """Return violations for weak tests and unreferenced critical functions."""
    sources = _test_sources(root, test_paths)
    violations = list(_assertion_violations(sources))
    violations.extend(_critical_reference_violations(root, sources))
    return tuple(violations)


def _assertion_violations(
    sources: list[tuple[str, str, ast.Module]],
) -> list[Violation]:
    violations: list[Violation] = []
    for relative, _text, tree in sources:
        for node in _test_functions(tree):
            if not _has_assertion(node):
                violations.append(
                    Violation(
                        message=f"{node.name} has no assertions",
                        file=relative,
                        line=node.lineno,
                        code="no-assert",
                        fix_hint=(
                            "assert on behavior; a test that cannot fail "
                            "verifies nothing"
                        ),
                    )
                )
    return violations


def _critical_reference_violations(
    root: Path,
    sources: list[tuple[str, str, ast.Module]],
) -> list[Violation]:
    critical = _public_critical_names(root)
    if not critical:
        return []
    corpus = "\n".join(text for _relative, text, _tree in sources)
    violations: list[Violation] = []
    for qualname in critical:
        simple = qualname.rsplit(".", 1)[-1]
        if simple not in corpus:
            violations.append(
                Violation(
                    message=f"no test references critical function {qualname}",
                    code="critical-untested",
                    fix_hint=f"add a test exercising {simple} directly",
                )
            )
    return violations


def _test_sources(
    root: Path,
    test_paths: tuple[str, ...],
) -> list[tuple[str, str, ast.Module]]:
    sources: list[tuple[str, str, ast.Module]] = []
    for test_path in test_paths:
        test_root = root / test_path
        if not test_root.is_dir():
            continue
        for path in sorted(test_root.rglob("test_*.py")):
            text = path.read_text()
            try:
                tree = ast.parse(text, filename=str(path))
            except SyntaxError:
                continue
            sources.append((str(path.relative_to(root)), text, tree))
    return sources


def _test_functions(tree: ast.Module) -> list[_TestFunction]:
    found: list[_TestFunction] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test_"):
                found.append(node)
    return found


def _has_assertion(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.Call) and _is_assert_call(child):
            return True
    return False


def _is_assert_call(call: ast.Call) -> bool:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    return func.attr == "raises" or func.attr.startswith("assert")


def _public_critical_names(root: Path) -> list[str]:
    names: list[str] = []
    for entry in read_json(root):
        if not entry.get("is_critical"):
            continue
        name = str(entry.get("name", ""))
        if name and not any(part.startswith("_") for part in name.split(".")):
            names.append(name)
    return names
