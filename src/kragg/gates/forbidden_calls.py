"""Forbidden-calls gate: APIs the project has banned, resolved deterministically.

The policy maps fully-qualified dotted paths to project-specific fix hints:

    [tool.kragg.forbidden_calls]
    "starlette.requests.Request.body" = "read bodies via app.http.read_limited_body"
    "subprocess.run" = "run external commands through app.runner.run_command"

An entry bans the exact callable and everything beneath it: ``pickle`` bans
``pickle.loads``, a class path bans every method. Resolution is name-based and
deterministic — precision over recall, like the criticality graph:

- imported names and module aliases resolve through the import table;
- ``obj.method()`` resolves when ``obj`` has a known class from a parameter
  annotation, an annotated assignment, or a ``name = package.Class(...)``
  constructor assignment (capitalized final segment);
- ``self.method()`` and unresolvable receivers are ignored, never guessed.

Re-exports are distinct names: banning ``starlette.requests.Request.body``
does not ban ``fastapi.Request.body`` — list every path the project imports.
The approved wrapper's own call site is the one place the raw API is
legitimate; mark it with a trailing ``# kragg: ignore``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from kragg.gates.criticality import module_imports, module_name
from kragg.gates.suppress import suppressed
from kragg.models import Violation

type _AnyFunction = ast.FunctionDef | ast.AsyncFunctionDef
type _ScopeParts = tuple[list[ast.AST], list[_AnyFunction], list[ast.ClassDef]]

_DEFAULT_HINT = "this API is forbidden by the project policy"


def check_forbidden_calls(
    root: Path,
    source_paths: tuple[str, ...],
    forbidden: tuple[tuple[str, str], ...],
) -> tuple[Violation, ...]:
    """Return one violation per call resolving to a forbidden dotted path."""
    if not forbidden:
        return ()
    rules = dict(forbidden)
    violations: list[Violation] = []
    for source in source_paths:
        base = root / source
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            violations.extend(_scan(path, base, root, rules))
    return tuple(violations)


def _scan(
    path: Path,
    src_root: Path,
    root: Path,
    rules: dict[str, str],
) -> list[Violation]:
    text = path.read_text()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    module = module_name(path, src_root)
    scanner = _Scanner(
        module=module,
        imports=module_imports(module, tree),
        rules=rules,
        lines=text.splitlines(),
        relative=str(path.relative_to(root)),
    )
    scanner.scan(tree.body, {})
    return sorted(scanner.violations, key=lambda violation: violation.line or 0)


@dataclass
class _Scanner:
    """Walks one module scope-by-scope, resolving calls against the rules."""

    module: str
    imports: dict[str, str]
    rules: dict[str, str]
    lines: list[str]
    relative: str
    violations: list[Violation] = field(default_factory=list)

    def scan(self, body: list[ast.stmt], inherited: dict[str, str]) -> None:
        nodes, functions, classes = _split_scope(body)
        types = dict(inherited)
        for node in nodes:
            self._record_binding(node, types)
        for node in nodes:
            if isinstance(node, ast.Call):
                self._check_call(node, types)
        for function in functions:
            self.scan(function.body, {**types, **self._parameter_types(function)})
        for cls in classes:
            self.scan(cls.body, types)

    def _record_binding(self, node: ast.AST, types: dict[str, str]) -> None:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            annotated = self._annotation_path(node.annotation)
            if annotated is not None:
                types[node.target.id] = annotated
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
        ):
            constructed = self._constructor_path(node.value.func, types)
            if constructed is not None:
                types[node.targets[0].id] = constructed

    def _check_call(self, node: ast.Call, types: dict[str, str]) -> None:
        resolved = self._resolve(node.func, types)
        if resolved is None:
            return
        entry = _matching_rule(resolved, self.rules)
        if entry is None or suppressed(self.lines, node):
            return
        banned = f" (banned: `{entry}`)" if entry != resolved else ""
        self.violations.append(
            Violation(
                message=f"forbidden call `{resolved}`{banned}",
                file=self.relative,
                line=node.lineno,
                code="forbidden-call",
                fix_hint=self.rules[entry] or _DEFAULT_HINT,
            )
        )

    def _resolve(self, func: ast.expr, types: dict[str, str]) -> str | None:
        parts: list[str] = []
        node = func
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        parts.reverse()
        if not parts:
            return self.imports.get(node.id, f"{self.module}.{node.id}")
        if node.id == "self":
            return None
        base = types.get(node.id) or self.imports.get(node.id)
        if base is None:
            return None
        return ".".join([base, *parts])

    def _constructor_path(
        self,
        func: ast.expr,
        types: dict[str, str],
    ) -> str | None:
        """Resolve ``name = pkg.Class(...)``; a lowercase tail is a plain call."""
        resolved = self._resolve(func, types)
        if resolved is None:
            return None
        tail = resolved.rsplit(".", 1)[-1]
        return resolved if tail[:1].isupper() else None

    def _annotation_path(self, annotation: ast.expr) -> str | None:
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            left = self._annotation_path(annotation.left)
            right = self._annotation_path(annotation.right)
            if left is not None and right is not None:
                return None
            return left if left is not None else right
        if isinstance(annotation, ast.Name | ast.Attribute):
            return self._resolve(annotation, {})
        return None

    def _parameter_types(self, function: _AnyFunction) -> dict[str, str]:
        args = function.args
        types: dict[str, str] = {}
        for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if arg.annotation is None:
                continue
            annotated = self._annotation_path(arg.annotation)
            if annotated is not None:
                types[arg.arg] = annotated
        return types


def _split_scope(body: list[ast.stmt]) -> _ScopeParts:
    """Partition a scope into its own nodes and the nested defs it owns.

    Decorator expressions evaluate in the enclosing scope, so they stay with
    the current scope's nodes; function and class bodies become child scopes.
    """
    nodes: list[ast.AST] = []
    functions: list[_AnyFunction] = []
    classes: list[ast.ClassDef] = []
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions.append(node)
            stack.extend(node.decorator_list)
        elif isinstance(node, ast.ClassDef):
            classes.append(node)
            stack.extend(node.decorator_list)
        else:
            nodes.append(node)
            stack.extend(ast.iter_child_nodes(node))
    return nodes, functions, classes


def _matching_rule(resolved: str, rules: dict[str, str]) -> str | None:
    """Most specific entry matching the call: exact or dotted-prefix ban."""
    matches = [
        entry
        for entry in rules
        if resolved == entry or resolved.startswith(f"{entry}.")
    ]
    return max(matches, key=len) if matches else None
