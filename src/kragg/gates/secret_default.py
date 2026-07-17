"""Secret-default gate: secret-named bindings that silently fall back.

A secret with a fallback default never fails loudly: ``os.environ.get(
"HMAC_SECRET", "")`` runs happily unconfigured and signs with an empty key,
and ``signing_secret: str = ""`` in a settings class does the same. This
gate flags the idiom — a secret-suffixed name given a default — at the
places configuration is born:

- ``os.environ.get(name, default)`` / ``os.getenv(name, default)`` where the
  literal name matches a secret suffix and any non-``None`` default is given;
- annotated or plain assignments binding a secret-suffixed name to a string
  literal (settings-class fields, module constants);
- function parameters whose secret-suffixed name defaults to a string literal.

``None`` defaults stay legal: they model "absent" honestly and force the
caller to handle the missing case. Suffixes come from the policy's
``secret_name_suffixes``; a name also matches its bare form (``password``
matches ``_password``). Reads through other dicts (``config.get(...)``)
are out of scope — no taint analysis, the idiom only. Suppress a reviewed
site with a trailing ``# kragg: ignore``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from kragg.gates.criticality import module_imports, module_name
from kragg.gates.forbidden_calls import resolve_call
from kragg.gates.suppress import suppressed
from kragg.models import Violation

_ENV_READS = ("os.environ.get", "os.getenv")
_FIX_HINT = (
    "read it with no default so startup fails loudly, "
    "or validate it non-empty at the boundary"
)


def check_secret_defaults(
    root: Path,
    source_paths: tuple[str, ...],
    suffixes: tuple[str, ...],
) -> tuple[Violation, ...]:
    """Return violations for secret-named bindings given silent defaults."""
    violations: list[Violation] = []
    for source in source_paths:
        base = root / source
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            violations.extend(_scan(path, base, root, suffixes))
    return tuple(violations)


def _scan(
    path: Path,
    src_root: Path,
    root: Path,
    suffixes: tuple[str, ...],
) -> list[Violation]:
    text = path.read_text()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    module = module_name(path, src_root)
    imports = module_imports(module, tree)
    lines = text.splitlines()
    relative = str(path.relative_to(root))
    violations: list[Violation] = []
    for node in ast.walk(tree):
        for name, default, flagged in _findings(node, module, imports, suffixes):
            if suppressed(lines, flagged):
                continue
            violations.append(_violation(name, default, relative, flagged))
    return sorted(violations, key=lambda violation: violation.line or 0)


type _Finding = tuple[str, ast.expr, ast.expr | ast.stmt]


def _findings(
    node: ast.AST,
    module: str,
    imports: dict[str, str],
    suffixes: tuple[str, ...],
) -> list[_Finding]:
    """Return (secret name, default expression, node to report) triples."""
    if isinstance(node, ast.Call):
        return _env_read_default(node, module, imports, suffixes)
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return _literal_binding(node.target.id, node.value, node, suffixes)
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return _literal_binding(node.targets[0].id, node.value, node, suffixes)
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return _parameter_defaults(node.args, suffixes)
    return []


def _env_read_default(
    node: ast.Call,
    module: str,
    imports: dict[str, str],
    suffixes: tuple[str, ...],
) -> list[_Finding]:
    if resolve_call(node.func, module, imports, {}) not in _ENV_READS:
        return []
    if not node.args:
        return []
    name = node.args[0]
    if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
        return []
    default = _call_default(node)
    if default is None or _is_none(default):
        return []
    if not _is_secret_name(name.value, suffixes):
        return []
    return [(name.value, default, node)]


def _call_default(node: ast.Call) -> ast.expr | None:
    if len(node.args) >= 2:
        return node.args[1]
    for keyword in node.keywords:
        if keyword.arg == "default":
            return keyword.value
    return None


def _literal_binding(
    name: str,
    value: ast.expr | None,
    node: ast.stmt,
    suffixes: tuple[str, ...],
) -> list[_Finding]:
    if value is None or not _is_str_literal(value):
        return []
    if not _is_secret_name(name, suffixes):
        return []
    return [(name, value, node)]


def _parameter_defaults(
    args: ast.arguments,
    suffixes: tuple[str, ...],
) -> list[_Finding]:
    positional = [*args.posonlyargs, *args.args]
    defaulted = positional[len(positional) - len(args.defaults) :]
    pairs = [
        *zip(defaulted, args.defaults, strict=True),
        *[
            (arg, default)
            for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
            if default is not None
        ],
    ]
    return [
        (arg.arg, default, default)
        for arg, default in pairs
        if _is_str_literal(default) and _is_secret_name(arg.arg, suffixes)
    ]


def _violation(
    name: str,
    default: ast.expr,
    relative: str,
    flagged: ast.expr | ast.stmt,
) -> Violation:
    empty = isinstance(default, ast.Constant) and default.value == ""
    problem = (
        "silently defaults to empty" if empty else "has a hardcoded fallback default"
    )
    return Violation(
        message=f"secret `{name}` {problem}",
        file=relative,
        line=flagged.lineno,
        code="secret-default",
        fix_hint=_FIX_HINT,
    )


def _is_secret_name(name: str, suffixes: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(
        lowered.endswith(suffix) or lowered == suffix.lstrip("_")
        for suffix in suffixes
    )


def _is_str_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None
