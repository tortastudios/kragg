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
  constructor assignment (capitalized final segment). Types are tracked in
  source order and any rebinding — assignment, loop or ``with`` target,
  lambda parameter, comprehension target — clears the tracked type;
- class-body bindings are not visible inside method bodies (Python scoping);
- ``self.method()`` and unresolvable receivers are ignored, never guessed.

Re-exports are distinct names: banning ``starlette.requests.Request.body``
does not ban ``fastapi.Request.body`` — list every path the project imports.
The approved wrapper's own call site is the one place the raw API is
legitimate; mark it with a trailing ``# kragg: ignore``.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from kragg.gates.sources import ParsedSource, parsed_sources
from kragg.gates.suppress import suppressed
from kragg.models import Violation

type _AnyFunction = ast.FunctionDef | ast.AsyncFunctionDef
type _Types = dict[str, str]

_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
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
    for source in parsed_sources(root, source_paths):
        scanner = _Scanner(source, rules)
        scanner.scan(source.tree.body, {}, is_class=False)
        violations.extend(
            sorted(scanner.violations, key=lambda violation: violation.line or 0)
        )
    return tuple(violations)


@dataclass
class _Scanner:
    """Walks one module scope-by-scope, resolving calls against the rules."""

    source: ParsedSource
    rules: dict[str, str]
    violations: list[Violation] = field(default_factory=list)

    def scan(self, body: list[ast.stmt], inherited: _Types, is_class: bool) -> None:
        types = dict(inherited)
        functions: list[_AnyFunction] = []
        classes: list[ast.ClassDef] = []
        self._walk(body, types, functions, classes)
        # Class-body names are invisible inside method bodies: nested scopes
        # of a class see its enclosing scope, not the class scope.
        child = dict(inherited) if is_class else types
        for function in functions:
            scope = {**child, **self._parameter_types(function)}
            self.scan(function.body, scope, is_class=False)
        for cls in classes:
            self.scan(cls.body, child, is_class=True)

    def _walk(
        self,
        nodes: Sequence[ast.AST],
        types: _Types,
        functions: list[_AnyFunction],
        classes: list[ast.ClassDef],
    ) -> None:
        """Visit a scope's nodes in source order, tracking bindings as they occur.

        Nested function/class bodies are collected for their own scope pass;
        their decorators, parameter defaults, and base classes evaluate here.
        """
        for node in nodes:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                functions.append(node)
                here = [*node.decorator_list, *_argument_defaults(node.args)]
                self._walk(here, types, functions, classes)
            elif isinstance(node, ast.ClassDef):
                classes.append(node)
                keyword_values = [keyword.value for keyword in node.keywords]
                here = [*node.decorator_list, *node.bases, *keyword_values]
                self._walk(here, types, functions, classes)
            elif isinstance(node, ast.Lambda):
                shadows = {arg.arg for arg in _all_arguments(node.args)}
                here = [*_argument_defaults(node.args), node.body]
                self._walk(here, _without(types, shadows), functions, classes)
            elif isinstance(node, _COMPREHENSIONS):
                shadows = _target_names([gen.target for gen in node.generators])
                children = list(ast.iter_child_nodes(node))
                self._walk(children, _without(types, shadows), functions, classes)
            else:
                if isinstance(node, ast.Call):
                    self._check_call(node, types)
                self._record_binding(node, types)
                children = list(ast.iter_child_nodes(node))
                self._walk(children, types, functions, classes)

    def _record_binding(self, node: ast.AST, types: _Types) -> None:
        """Track name → class bindings; any rebinding clears the old type."""
        for name in _rebound_names(node):
            types.pop(name, None)
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

    def _check_call(self, node: ast.Call, types: _Types) -> None:
        resolved = self._resolve(node.func, types)
        if resolved is None:
            return
        rule = _matching_rule(resolved, self.rules)
        if rule is None or suppressed(self.source.lines, node):
            return
        entry, hint = rule
        banned = f" (banned: `{entry}`)" if entry != resolved else ""
        self.violations.append(
            Violation(
                message=f"forbidden call `{resolved}`{banned}",
                file=self.source.relative,
                line=node.lineno,
                code="forbidden-call",
                fix_hint=hint or _DEFAULT_HINT,
            )
        )

    def _resolve(self, func: ast.expr, types: _Types) -> str | None:
        return resolve_call(func, self.source.module, self.source.imports, types)

    def _constructor_path(self, func: ast.expr, types: _Types) -> str | None:
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

    def _parameter_types(self, function: _AnyFunction) -> _Types:
        types: _Types = {}
        for arg in _all_arguments(function.args):
            if arg.annotation is None:
                continue
            annotated = self._annotation_path(arg.annotation)
            if annotated is not None:
                types[arg.arg] = annotated
        return types


def resolve_call(
    func: ast.expr,
    module: str,
    imports: dict[str, str],
    types: dict[str, str],
) -> str | None:
    """Resolve a callable expression to a dotted path; None when unresolvable.

    Bare names resolve through the import table, falling back to the defining
    module; attribute chains resolve their base through known local types
    (annotations, constructor assignments) and then the import table.
    """
    parts: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.reverse()
    if not parts:
        return imports.get(node.id, f"{module}.{node.id}")
    if node.id == "self":
        return None
    base = types.get(node.id) or imports.get(node.id)
    if base is None:
        return None
    return ".".join([base, *parts])


def _matching_rule(resolved: str, rules: dict[str, str]) -> tuple[str, str] | None:
    """Most specific entry matching the call: exact or dotted-prefix ban."""
    matches = [
        entry
        for entry in rules
        if resolved == entry or resolved.startswith(f"{entry}.")
    ]
    if not matches:
        return None
    entry = max(matches, key=len)
    return entry, rules[entry]


def _rebound_names(node: ast.AST) -> set[str]:
    """Names a statement rebinds — assignments, loop and ``with`` targets."""
    if isinstance(node, ast.Assign):
        return _target_names(node.targets)
    if isinstance(node, ast.AnnAssign | ast.AugAssign):
        return _target_names([node.target])
    if isinstance(node, ast.For | ast.AsyncFor):
        return _target_names([node.target])
    if isinstance(node, ast.With | ast.AsyncWith):
        bound = [item.optional_vars for item in node.items if item.optional_vars]
        return _target_names(bound)
    return set()


def _target_names(targets: list[ast.expr]) -> set[str]:
    """Every plain name bound by the targets, through tuple/star nesting."""
    names: set[str] = set()
    stack = list(targets)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Starred):
            stack.append(node.value)
        elif isinstance(node, ast.Tuple | ast.List):
            stack.extend(node.elts)
    return names


def _argument_defaults(args: ast.arguments) -> list[ast.expr]:
    """Default expressions, which evaluate in the enclosing scope."""
    keyword_defaults = [default for default in args.kw_defaults if default is not None]
    return [*args.defaults, *keyword_defaults]


def _all_arguments(args: ast.arguments) -> list[ast.arg]:
    return [*args.posonlyargs, *args.args, *args.kwonlyargs]


def _without(types: _Types, names: set[str]) -> _Types:
    return {name: path for name, path in types.items() if name not in names}
