"""Secret-default gate: secret-named bindings that silently fall back.

A secret with a fallback default never fails loudly: ``os.environ.get(
"HMAC_SECRET", "")`` runs happily unconfigured and signs with an empty key,
and ``signing_secret: str = ""`` in a settings class does the same. This
gate flags the idiom — a secret-suffixed name given a default — at the
places configuration is born:

- ``os.environ.get(name, default)`` / ``os.getenv(name, default)`` where the
  literal name matches a secret suffix and any non-``None`` default is given;
- assignments binding a secret-suffixed name or attribute (``self.api_key``)
  to a string literal, including chained targets and annotated fields;
- function and lambda parameters whose secret-suffixed name defaults to a
  string literal.

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

from kragg.gates.forbidden_calls import resolve_call
from kragg.gates.sources import ParsedSource, parsed_sources
from kragg.gates.suppress import suppressed
from kragg.models import Violation

type _Finding = tuple[str, bool, ast.expr | ast.stmt]

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
    if not suffixes:
        return ()
    violations: list[Violation] = []
    for source in parsed_sources(root, source_paths):
        violations.extend(_scan(source, suffixes))
    return tuple(violations)


def _scan(source: ParsedSource, suffixes: tuple[str, ...]) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(source.tree):
        for name, empty, flagged in _findings(node, source, suffixes):
            if suppressed(source.lines, flagged):
                continue
            violations.append(_violation(name, empty, source.relative, flagged))
    return sorted(violations, key=lambda violation: violation.line or 0)


def _findings(
    node: ast.AST,
    source: ParsedSource,
    suffixes: tuple[str, ...],
) -> list[_Finding]:
    """Return (secret name, empty default, node to report) triples."""
    if isinstance(node, ast.Call):
        return _env_read_default(node, source, suffixes)
    if isinstance(node, ast.AnnAssign):
        return _literal_binding(_target_name(node.target), node.value, node, suffixes)
    if isinstance(node, ast.Assign):
        findings: list[_Finding] = []
        for target in node.targets:
            found = _literal_binding(_target_name(target), node.value, node, suffixes)
            findings.extend(found)
        return findings
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        return _parameter_defaults(node.args, suffixes)
    return []


def _env_read_default(
    node: ast.Call,
    source: ParsedSource,
    suffixes: tuple[str, ...],
) -> list[_Finding]:
    if not node.args:
        return []
    name = node.args[0]
    if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
        return []
    if not _is_secret_name(name.value, suffixes):
        return []
    default = _call_default(node)
    if default is None or _is_none(default):
        return []
    if resolve_call(node.func, source.module, source.imports, {}) not in _ENV_READS:
        return []
    return [(name.value, _is_empty_str(default), node)]


def _call_default(node: ast.Call) -> ast.expr | None:
    if len(node.args) >= 2:
        return node.args[1]
    for keyword in node.keywords:
        if keyword.arg == "default":
            return keyword.value
    return None


def _target_name(target: ast.expr) -> str | None:
    """Name bound by an assignment target: a plain name or an attribute."""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _literal_binding(
    name: str | None,
    value: ast.expr | None,
    node: ast.stmt,
    suffixes: tuple[str, ...],
) -> list[_Finding]:
    if name is None or value is None or not _is_str_literal(value):
        return []
    if not _is_secret_name(name, suffixes):
        return []
    return [(name, _is_empty_str(value), node)]


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
        (arg.arg, _is_empty_str(default), default)
        for arg, default in pairs
        if _is_str_literal(default) and _is_secret_name(arg.arg, suffixes)
    ]


def _violation(
    name: str,
    empty: bool,
    relative: str,
    flagged: ast.expr | ast.stmt,
) -> Violation:
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


def _is_empty_str(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == ""


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None
