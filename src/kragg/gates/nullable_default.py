"""Nullable-default gate: dict arithmetic a present-but-null value would break.

``d.get(key, default)`` returns ``default`` only when the key is ABSENT — when
the key is present with value ``None``/``null`` it returns ``None``. So
``a.get("x", 0) + b.get("x", 0)`` raises ``TypeError: unsupported operand
type(s) for +: 'int' and 'NoneType'`` the instant the source yields null. This
gate flags arithmetic where BOTH operands are dict accessors and at least one is
a ``.get(key, <non-None default>)``.

Honest scope: this matches the IDIOM, not "external data" — kragg has no taint
analysis, so it cannot know whether a dict came from an API or a local literal.
To stay precise (measured against a real 206-file production repo) it:
  * excludes the accumulator ``d.get(k, 0) + 1`` — one operand is a literal;
  * treats ALL-CAPS receivers (``WEIGHTS.get(...)``) as constant maps, not data.
Residual false positives on internal dicts: suppress with a trailing
``# kragg: ignore``. See ``KNOWN_LIMITATIONS.md`` for what this cannot catch.
"""

from __future__ import annotations

import ast
from pathlib import Path

from kragg.gates.suppress import suppressed
from kragg.models import Violation

_ARITH: tuple[type[ast.operator], ...] = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
)


def check_nullable_defaults(
    root: Path,
    source_paths: tuple[str, ...],
) -> tuple[Violation, ...]:
    """Return violations for dict-arithmetic that breaks on a present-but-null."""
    violations: list[Violation] = []
    for source in source_paths:
        base = root / source
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            violations.extend(_scan(path, root))
    return tuple(violations)


def _scan(path: Path, root: Path) -> list[Violation]:
    text = path.read_text()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, _ARITH)):
            continue
        operands = (node.left, node.right)
        if not all(_is_accessor(operand) for operand in operands):
            continue
        if not any(_is_dangerous_get(operand) for operand in operands):
            continue
        if suppressed(lines, node):
            continue
        violations.append(
            Violation(
                message=(
                    "arithmetic on `.get(key, default)` results crashes when the "
                    "key is present-but-null"
                ),
                file=str(path.relative_to(root)),
                line=node.lineno,
                code="nullable-default",
                fix_hint=(
                    "type the field `T | None` and coerce, or "
                    "`x if x is not None else default` — never `or`"
                ),
            )
        )
    return violations


def _is_accessor(node: ast.expr) -> bool:
    if _is_dangerous_get(node):
        return True
    return isinstance(node, ast.Subscript) and not _is_constant(node.value)


def _is_dangerous_get(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "get"):
        return False
    if len(node.args) != 2 or node.keywords:
        return False
    return _is_nonnull_literal(node.args[1]) and not _is_constant(func.value)


def _is_nonnull_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is not None
    return isinstance(node, ast.List | ast.Dict | ast.Tuple | ast.Set)


def _is_constant(node: ast.expr) -> bool:
    """A receiver named in ALL_CAPS is a module constant, not external data."""
    return (
        isinstance(node, ast.Name)
        and node.id.isupper()
        and any(char.isalpha() for char in node.id)
    )
