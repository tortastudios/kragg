from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TypeViolation:
    """A single type annotation complexity violation."""

    file_path: Path
    line: int
    context: str
    annotation_text: str
    depth: int
    length: int
    suggestion: str


def compute_depth(node: ast.expr) -> int:
    """Return the nesting depth of a type annotation AST node."""
    if isinstance(node, ast.Subscript):
        return 1 + compute_depth(node.slice)
    if isinstance(node, ast.Tuple):
        if not node.elts:
            return 0
        return max(compute_depth(element) for element in node.elts)
    return 0


def suggest_fix(annotation_text: str, depth: int, max_depth: int) -> str:
    """Return a concrete suggestion based on annotation shape."""
    normalized = annotation_text.lower()
    has_dict = "dict" in normalized
    has_list = "list" in normalized
    dict_count = normalized.count("dict")

    if has_dict and has_list:
        return "Extract into a @dataclass with named fields"
    if dict_count >= 2:
        return "Use a TypedDict or @dataclass instead of nested dicts"
    if depth <= max_depth:
        return "Define a TypeAlias to name this shape"
    return "Simplify with a @dataclass or TypeAlias"


def check_annotation(
    node: ast.expr,
    file_path: Path,
    line: int,
    context: str,
    max_depth: int,
    max_length: int,
) -> TypeViolation | None:
    """Check one annotation node and return a violation if it fails."""
    text = ast.unparse(node)
    depth = compute_depth(node)
    length = len(text)

    if depth > max_depth or length > max_length:
        return TypeViolation(
            file_path=file_path,
            line=line,
            context=context,
            annotation_text=text,
            depth=depth,
            length=length,
            suggestion=suggest_fix(text, depth, max_depth),
        )
    return None


def check_file(path: Path, max_depth: int, max_length: int) -> list[TypeViolation]:
    """Parse a Python file and return all annotation violations."""
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return []

    violations: list[TypeViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and node.annotation:
            target = ast.unparse(node.target)
            violation = check_annotation(
                node.annotation,
                path,
                node.lineno,
                f"variable '{target}'",
                max_depth,
                max_length,
            )
            if violation:
                violations.append(violation)

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _check_function(node, path, violations, max_depth, max_length)

    return violations


def check_path(target: Path, max_depth: int, max_length: int) -> list[TypeViolation]:
    """Check a file or directory for type annotation complexity violations."""
    if target.is_dir():
        files = sorted(target.rglob("*.py"))
    elif target.is_file():
        files = [target]
    else:
        return [
            TypeViolation(
                file_path=target,
                line=0,
                context="path",
                annotation_text="",
                depth=0,
                length=0,
                suggestion="Path not found",
            )
        ]

    violations: list[TypeViolation] = []
    for file_path in files:
        violations.extend(check_file(file_path, max_depth, max_length))
    return violations


def format_violation(violation: TypeViolation) -> str:
    """Format a violation for CLI output."""
    if violation.line == 0:
        return f"  {violation.file_path}: {violation.suggestion}"
    return "\n".join(
        [
            f"  {violation.file_path}:{violation.line}  {violation.context}",
            f"    annotation: {violation.annotation_text}",
            f"    depth={violation.depth}  length={violation.length}",
            f"    -> {violation.suggestion}",
        ]
    )


def _check_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    violations: list[TypeViolation],
    max_depth: int,
    max_length: int,
) -> None:
    for arg in [*node.args.args, *node.args.kwonlyargs]:
        if arg.annotation:
            violation = check_annotation(
                arg.annotation,
                file_path,
                arg.lineno,
                f"argument '{arg.arg}' in {node.name}()",
                max_depth,
                max_length,
            )
            if violation:
                violations.append(violation)

    if node.returns:
        violation = check_annotation(
            node.returns,
            file_path,
            node.lineno,
            f"return type of {node.name}()",
            max_depth,
            max_length,
        )
        if violation:
            violations.append(violation)
