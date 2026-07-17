"""Shared `# kragg: ignore` suppression for native AST gates.

A reviewed-safe site is silenced with a trailing ``# kragg: ignore`` on any
line the flagged node spans. Suppression is per-site and visible in diffs,
so every exemption is reviewable where it happens.
"""

from __future__ import annotations

import ast

SUPPRESS_COMMENT = "# kragg: ignore"


def suppressed(lines: list[str], node: ast.expr | ast.stmt) -> bool:
    """True when any line spanned by the node carries the suppress comment."""
    end = node.end_lineno or node.lineno
    return any(
        SUPPRESS_COMMENT in lines[index]
        for index in range(node.lineno - 1, end)
        if 0 <= index < len(lines)
    )
