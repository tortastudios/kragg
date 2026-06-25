"""Typing-strictness gate: make ``strict-ai-python`` a verified contract.

kragg's mypy gate is only as strong as the project's mypy config, and the
scaffold historically shipped none — so a lax or absent ``[tool.mypy]`` let
``dict[str, Any]`` external data pass trivially. This gate deterministically
audits that the project actually meets the strict floor and has not planted
escape hatches (``ignore_errors``, loosened core flags, bare ``# type: ignore``)
that would silence the type checker.

It does NOT do type inference or taint analysis — it audits configuration and
scans for blanket ignores. Honest residual: a value typed ``int`` that is
really nullable still passes; see ``KNOWN_LIMITATIONS.md``.
"""

from __future__ import annotations

import io
import re
import tokenize
import tomllib
from pathlib import Path
from typing import cast

from kragg.models import Violation

# Flags implied by ``strict = true``; an explicit ``flag = false`` re-opens the
# hole even under strict, so each is audited for downgrade.
_CORE_FLAGS = (
    "disallow_untyped_defs",
    "check_untyped_defs",
    "warn_return_any",
    "disallow_any_generics",
)
_BARE_IGNORE = re.compile(r"#\s*type:\s*ignore\b(?!\[)")


def check_typing_strictness(
    root: Path,
    source_paths: tuple[str, ...],
) -> tuple[Violation, ...]:
    """Return violations where the project falls below the strict-typing floor."""
    violations = _config_violations(root)
    violations.extend(_bare_ignore_violations(root, source_paths))
    return tuple(violations)


def _config_violations(root: Path) -> list[Violation]:
    mypy = _mypy_table(root)
    if mypy is None:
        return [
            Violation(
                message="no strict `[tool.mypy]` config (mypy gate is toothless)",
                file="pyproject.toml",
                code="mypy-config-missing",
                fix_hint="add `[tool.mypy]` with `strict = true` (see kragg scaffold)",
            )
        ]
    violations: list[Violation] = []
    if not _meets_floor(mypy):
        violations.append(
            Violation(
                message="mypy is not strict (missing `strict = true`)",
                file="pyproject.toml",
                code="mypy-not-strict",
                fix_hint="set `strict = true` under [tool.mypy]",
            )
        )
    violations.extend(_loosening(mypy, "[tool.mypy]"))
    overrides = mypy.get("overrides")
    if isinstance(overrides, list):
        for entry in overrides:
            if isinstance(entry, dict):
                table = cast("dict[str, object]", entry)
                violations.extend(_loosening(table, "[[tool.mypy.overrides]]"))
    return violations


def _mypy_table(root: Path) -> dict[str, object] | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text())
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return None
    mypy = tool.get("mypy")
    if not isinstance(mypy, dict):
        return None
    return cast("dict[str, object]", mypy)


def _meets_floor(mypy: dict[str, object]) -> bool:
    if mypy.get("strict") is True:
        return True
    return all(mypy.get(flag) is True for flag in _CORE_FLAGS)


def _loosening(table: dict[str, object], scope: str) -> list[Violation]:
    """Flag escape hatches. ``ignore_missing_imports`` is intentionally allowed:
    it only suppresses third-party import errors, not the project's own types.
    """
    violations: list[Violation] = []
    if table.get("ignore_errors") is True:
        violations.append(
            Violation(
                message=f"{scope} sets `ignore_errors = true` — silences type checks",
                file="pyproject.toml",
                code="mypy-ignore-errors",
                fix_hint="remove `ignore_errors`; fix the types instead",
            )
        )
    for flag in (*_CORE_FLAGS, "strict"):
        if table.get(flag) is False:
            violations.append(
                Violation(
                    message=f"{scope} disables `{flag}` — re-opens the typing hole",
                    file="pyproject.toml",
                    code="mypy-loosened",
                    fix_hint=f"remove `{flag} = false`; keep the strict floor",
                )
            )
    return violations


def _bare_ignore_violations(
    root: Path,
    source_paths: tuple[str, ...],
) -> list[Violation]:
    violations: list[Violation] = []
    for source in source_paths:
        base = root / source
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            violations.extend(_scan_bare_ignores(path, root))
    return violations


def _scan_bare_ignores(path: Path, root: Path) -> list[Violation]:
    # Match the directive only as a real COMMENT token, never inside a string or
    # docstring — this module necessarily documents the pattern it detects.
    violations: list[Violation] = []
    try:
        readline = io.StringIO(path.read_text()).readline
        for token in tokenize.generate_tokens(readline):
            if token.type == tokenize.COMMENT and _BARE_IGNORE.match(token.string):
                violations.append(
                    Violation(
                        message="bare `# type: ignore` hides an unknown error",
                        file=str(path.relative_to(root)),
                        line=token.start[0],
                        code="bare-type-ignore",
                        fix_hint="pin the code: `# type: ignore[error-code]`",
                    )
                )
    except (tokenize.TokenError, SyntaxError, UnicodeDecodeError):
        return []
    return violations
