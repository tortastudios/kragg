"""Architecture gates: layered import contracts and structural budgets.

Layers are declared top-to-bottom in ``[tool.crag] layers`` as module
prefixes, e.g. ``["app.entrypoints", "app.services", "app.domain"]``.
A module in a layer may import its own layer or lower layers, never a
higher one. Modules outside every layer are unrestricted.

Structural budgets cap file length and public symbols per module so
god-files mechanically cannot accumulate.
"""

from __future__ import annotations

import ast
from pathlib import Path

from crag.gates.criticality import module_imports, module_name
from crag.models import Violation


def check_layers(
    root: Path,
    source_paths: tuple[str, ...],
    layers: tuple[str, ...],
) -> tuple[Violation, ...]:
    """Return one violation per import that crosses layers upward."""
    if len(layers) < 2:
        return ()
    violations: list[Violation] = []
    for path, module, tree in _source_modules(root, source_paths):
        layer = _layer_index(module, layers)
        if layer is None:
            continue
        for target in module_imports(module, tree).values():
            target_layer = _layer_index(target, layers)
            if target_layer is not None and target_layer < layer:
                violations.append(
                    Violation(
                        message=(
                            f"{module} (layer `{layers[layer]}`) imports "
                            f"{target} (layer `{layers[target_layer]}`)"
                        ),
                        file=str(path.relative_to(root)),
                        code="layer-breach",
                        fix_hint=(
                            "lower layers must not import higher layers; "
                            "invert the dependency or move the shared code down"
                        ),
                    )
                )
    return tuple(violations)


def check_structure(
    root: Path,
    source_paths: tuple[str, ...],
    max_file_lines: int,
    max_public_symbols: int,
) -> tuple[Violation, ...]:
    """Return violations for files exceeding structural budgets."""
    violations: list[Violation] = []
    for path, _module, tree in _source_modules(root, source_paths):
        relative = str(path.relative_to(root))
        lines = path.read_text().count("\n") + 1
        if lines > max_file_lines:
            violations.append(
                Violation(
                    message=f"file has {lines} lines (max {max_file_lines})",
                    file=relative,
                    code="file-budget",
                    fix_hint="split into smaller modules with single concerns",
                )
            )
        public = _public_symbols(tree)
        if len(public) > max_public_symbols:
            violations.append(
                Violation(
                    message=(
                        f"module exposes {len(public)} public symbols "
                        f"(max {max_public_symbols})"
                    ),
                    file=relative,
                    code="symbol-budget",
                    fix_hint=("split the module or prefix internals with underscores"),
                )
            )
    return tuple(violations)


def _source_modules(
    root: Path,
    source_paths: tuple[str, ...],
) -> list[tuple[Path, str, ast.Module]]:
    modules: list[tuple[Path, str, ast.Module]] = []
    for source in source_paths:
        src_root = root / source
        if not src_root.is_dir():
            continue
        for path in sorted(src_root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(), filename=str(path))
            except SyntaxError:
                continue
            modules.append((path, module_name(path, src_root), tree))
    return modules


def _layer_index(module: str, layers: tuple[str, ...]) -> int | None:
    for index, layer in enumerate(layers):
        if module == layer or module.startswith(f"{layer}."):
            return index
    return None


def _public_symbols(tree: ast.Module) -> list[str]:
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and not node.name.startswith("_")
    ]
