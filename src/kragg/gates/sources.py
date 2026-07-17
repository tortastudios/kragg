"""Shared per-file harness for native AST gates that resolve names.

One walk over the policy's source paths, yielding each parseable file with
the pieces a name-resolving gate needs (module path, import table, raw
lines for suppression checks). Gates that share this walk are guaranteed
to scan the same file set for the same policy.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from kragg.gates.criticality import module_imports, module_name


@dataclass(frozen=True)
class ParsedSource:
    """One parsed source file with everything a name-resolving gate needs."""

    path: Path
    relative: str
    module: str
    tree: ast.Module
    lines: list[str]
    imports: dict[str, str]


def parsed_sources(
    root: Path,
    source_paths: tuple[str, ...],
) -> Iterator[ParsedSource]:
    """Yield parsed files under the source paths, skipping broken syntax."""
    for source in source_paths:
        base = root / source
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            text = path.read_text()
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            module = module_name(path, base)
            yield ParsedSource(
                path=path,
                relative=str(path.relative_to(root)),
                module=module,
                tree=tree,
                lines=text.splitlines(),
                imports=module_imports(module, tree),
            )
