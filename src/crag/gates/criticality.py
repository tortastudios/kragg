"""Call-graph criticality analysis built on stdlib AST parsing.

Resolution is name-based and deterministic — precision over recall:

- bare calls resolve within the defining module, then through its imports
- ``self.method()`` resolves within the enclosing class
- ``obj.method()`` resolves when ``obj`` has a known class from a parameter
  annotation, an annotated assignment, or a direct constructor assignment
- constructor calls resolve to ``Class.__init__`` when defined, else to the
  class itself

Unresolvable calls are ignored rather than guessed, so strict typing in the
analyzed project directly improves graph completeness.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

type _ImportMap = dict[str, dict[str, str]]


@dataclass(frozen=True)
class FunctionProfile:
    """Call-graph metrics for a Python function or method."""

    name: str
    fan_in: int
    fan_out: int
    betweenness: float
    is_critical: bool

    @property
    def risk_label(self) -> str:
        if self.betweenness >= 0.2 or self.fan_in >= 5:
            return "HIGH"
        if self.betweenness >= 0.1 or self.fan_in >= 3:
            return "MED"
        return "low"


@dataclass
class _ProjectIndex:
    """Symbols defined across the analyzed source tree."""

    functions: set[str] = field(default_factory=set)
    classes: set[str] = field(default_factory=set)
    imports: _ImportMap = field(default_factory=dict)

    def resolve_import(self, module: str, name: str) -> str | None:
        return self.imports.get(module, {}).get(name)


@dataclass(frozen=True)
class _FunctionBody:
    """One function definition awaiting call extraction."""

    qualname: str
    module: str
    class_name: str | None
    node: ast.FunctionDef | ast.AsyncFunctionDef


def analyze(
    src_dir: Path,
    top_n: int = 20,
    fan_in_threshold: int = 3,
    betweenness_threshold: float = 0.1,
) -> list[FunctionProfile]:
    """Analyze call-graph centrality and return the riskiest functions."""
    graph = build_call_graph(src_dir)
    if graph.number_of_nodes() == 0:
        return []

    betweenness = nx.betweenness_centrality(graph, normalized=True)
    profiles: list[FunctionProfile] = []
    for node in graph.nodes:
        fan_in = graph.in_degree(node)
        centrality = betweenness.get(node, 0.0)
        profiles.append(
            FunctionProfile(
                name=node,
                fan_in=fan_in,
                fan_out=graph.out_degree(node),
                betweenness=centrality,
                is_critical=fan_in >= fan_in_threshold
                or centrality >= betweenness_threshold,
            )
        )

    ordered = sorted(profiles, key=lambda item: (item.betweenness, item.fan_in))
    return list(reversed(ordered))[:top_n]


def build_call_graph(src_dir: Path) -> nx.DiGraph[str]:
    """Build a directed call graph for every module under src_dir."""
    if not src_dir.is_dir():
        raise RuntimeError(f"source path not found: {src_dir}")
    modules = _parse_modules(src_dir)
    index = _build_index(modules)
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(index.functions)
    for body in _function_bodies(modules):
        _add_call_edges(graph, body, index)
    return graph


def _parse_modules(src_dir: Path) -> dict[str, ast.Module]:
    modules: dict[str, ast.Module] = {}
    for path in sorted(src_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        modules[_module_name(path, src_dir)] = tree
    return modules


def _module_name(path: Path, src_dir: Path) -> str:
    relative = path.relative_to(src_dir).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1] or [src_dir.name]
    return ".".join(parts)


def _build_index(modules: dict[str, ast.Module]) -> _ProjectIndex:
    index = _ProjectIndex()
    for module, tree in modules.items():
        index.imports[module] = _module_imports(module, tree)
        _index_definitions(index, module, tree, class_name=None)
    return index


def _index_definitions(
    index: _ProjectIndex,
    module: str,
    node: ast.AST,
    class_name: str | None,
) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            index.functions.add(_qualify(module, class_name, child.name))
        elif isinstance(child, ast.ClassDef):
            index.classes.add(f"{module}.{child.name}")
            _index_definitions(index, module, child, class_name=child.name)
        else:
            _index_definitions(index, module, child, class_name=class_name)


def _module_imports(module: str, tree: ast.Module) -> dict[str, str]:
    imports: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _record_plain_imports(imports, node)
        elif isinstance(node, ast.ImportFrom):
            _record_from_imports(imports, module, node)
    return imports


def _record_plain_imports(imports: dict[str, str], node: ast.Import) -> None:
    for alias in node.names:
        bound = alias.asname or alias.name.partition(".")[0]
        imports[bound] = alias.name if alias.asname else bound


def _record_from_imports(
    imports: dict[str, str],
    module: str,
    node: ast.ImportFrom,
) -> None:
    base = _import_from_base(module, node)
    if base is None:
        return
    for alias in node.names:
        if alias.name != "*":
            imports[alias.asname or alias.name] = f"{base}.{alias.name}"


def _import_from_base(module: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    parts = module.split(".")[: len(module.split(".")) - node.level]
    if node.module:
        parts.append(node.module)
    return ".".join(parts) if parts else None


def _function_bodies(modules: dict[str, ast.Module]) -> list[_FunctionBody]:
    bodies: list[_FunctionBody] = []
    for module, tree in modules.items():
        _collect_bodies(bodies, module, tree, class_name=None)
    return bodies


def _collect_bodies(
    bodies: list[_FunctionBody],
    module: str,
    node: ast.AST,
    class_name: str | None,
) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            qualname = _qualify(module, class_name, child.name)
            bodies.append(_FunctionBody(qualname, module, class_name, child))
        elif isinstance(child, ast.ClassDef):
            _collect_bodies(bodies, module, child, class_name=child.name)
        else:
            _collect_bodies(bodies, module, child, class_name=class_name)


def _add_call_edges(
    graph: nx.DiGraph[str],
    body: _FunctionBody,
    index: _ProjectIndex,
) -> None:
    local_types = _local_types(body, index)
    for node in ast.walk(body.node):
        if not isinstance(node, ast.Call):
            continue
        callee = _resolve_call(node.func, body, index, local_types)
        if callee is not None and callee != body.qualname:
            graph.add_edge(body.qualname, callee)


def _resolve_call(
    func: ast.expr,
    body: _FunctionBody,
    index: _ProjectIndex,
    local_types: dict[str, str],
) -> str | None:
    if isinstance(func, ast.Name):
        return _resolve_name(func.id, body.module, index)
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return _resolve_attribute(func.value.id, func.attr, body, index, local_types)
    return None


def _resolve_name(name: str, module: str, index: _ProjectIndex) -> str | None:
    local = f"{module}.{name}"
    if local in index.functions:
        return local
    if local in index.classes:
        return _constructor(local, index)
    target = index.resolve_import(module, name)
    if target is None:
        return None
    if target in index.functions:
        return target
    if target in index.classes:
        return _constructor(target, index)
    return None


def _resolve_attribute(
    base: str,
    attr: str,
    body: _FunctionBody,
    index: _ProjectIndex,
    local_types: dict[str, str],
) -> str | None:
    if base == "self" and body.class_name is not None:
        method = _qualify(body.module, body.class_name, attr)
        return method if method in index.functions else None
    receiver = local_types.get(base)
    if receiver is not None:
        method = f"{receiver}.{attr}"
        return method if method in index.functions else None
    target = index.resolve_import(body.module, base)
    if target is None:
        return None
    candidate = f"{target}.{attr}"
    if candidate in index.functions:
        return candidate
    if candidate in index.classes:
        return _constructor(candidate, index)
    return None


def _constructor(class_qualname: str, index: _ProjectIndex) -> str:
    init = f"{class_qualname}.__init__"
    return init if init in index.functions else class_qualname


def _local_types(body: _FunctionBody, index: _ProjectIndex) -> dict[str, str]:
    """Map local names to project classes via annotations and constructors."""
    types: dict[str, str] = {}
    args = body.node.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
        if arg.annotation is not None:
            _record_type(types, arg.arg, arg.annotation, body.module, index)
    for node in ast.walk(body.node):
        target = _single_name_target(node)
        if target is None:
            continue
        if isinstance(node, ast.AnnAssign):
            _record_type(types, target, node.annotation, body.module, index)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            _record_constructed_type(types, target, node.value, body.module, index)
    return types


def _single_name_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id
    return None


def _record_type(
    types: dict[str, str],
    name: str,
    annotation: ast.expr,
    module: str,
    index: _ProjectIndex,
) -> None:
    qualname = _annotation_class(annotation, module, index)
    if qualname is not None:
        types[name] = qualname


def _record_constructed_type(
    types: dict[str, str],
    name: str,
    call: ast.Call,
    module: str,
    index: _ProjectIndex,
) -> None:
    if isinstance(call.func, ast.Name):
        qualname = _annotation_class(call.func, module, index)
        if qualname is not None:
            types[name] = qualname


def _annotation_class(
    annotation: ast.expr,
    module: str,
    index: _ProjectIndex,
) -> str | None:
    if not isinstance(annotation, ast.Name):
        return None
    local = f"{module}.{annotation.id}"
    if local in index.classes:
        return local
    target = index.resolve_import(module, annotation.id)
    if target is not None and target in index.classes:
        return target
    return None


def _qualify(module: str, class_name: str | None, name: str) -> str:
    if class_name is not None:
        return f"{module}.{class_name}.{name}"
    return f"{module}.{name}"


def format_report(profiles: list[FunctionProfile]) -> str:
    """Format call-graph metrics as a Markdown report."""
    lines = [
        "# Critical Functions",
        "",
        "> Auto-generated by `crag criticality --write`. Do not edit by hand.",
        "",
        "Functions marked critical have high fan-in or betweenness centrality.",
        "When editing them, full types, docstrings, and tests are mandatory.",
        "",
    ]
    critical = [profile for profile in profiles if profile.is_critical]
    non_critical = [profile for profile in profiles if not profile.is_critical]

    if critical:
        lines.extend(_format_section("Critical", critical))
    if non_critical:
        lines.extend(_format_section("Non-critical", non_critical))
    if not profiles:
        lines.append("No functions found.")
    return "\n".join(lines) + "\n"


def write_report(profiles: list[FunctionProfile], output_path: Path) -> None:
    """Write a Markdown criticality report."""
    output_path.write_text(format_report(profiles))


def write_json(profiles: list[FunctionProfile], output_path: Path) -> None:
    """Write machine-readable criticality data for agents and hooks."""
    payload = [
        {
            "name": profile.name,
            "fan_in": profile.fan_in,
            "fan_out": profile.fan_out,
            "betweenness": round(profile.betweenness, 4),
            "is_critical": profile.is_critical,
            "risk": profile.risk_label,
        }
        for profile in profiles
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=1) + "\n")


def print_table(profiles: list[FunctionProfile]) -> None:
    """Print a compact text table to stdout."""
    if not profiles:
        print("No functions found.")
        return
    header = (
        f"{'Function':<55} {'Fan-in':>8} {'Fan-out':>8} {'Centrality':>12} {'Risk':>8}"
    )
    print(header)
    print("-" * 96)
    for profile in profiles:
        print(
            f"{profile.name:<55} {profile.fan_in:>8} {profile.fan_out:>8} "
            f"{profile.betweenness:>12.4f} {profile.risk_label:>8}"
        )


def _format_section(title: str, profiles: list[FunctionProfile]) -> list[str]:
    lines = [f"## {title}", ""]
    lines.append("| Function | Fan-in | Fan-out | Centrality | Risk |")
    lines.append("| --- | ---: | ---: | ---: | --- |")
    for profile in profiles:
        lines.append(
            f"| `{profile.name}` | {profile.fan_in} | {profile.fan_out} | "
            f"{profile.betweenness:.4f} | {profile.risk_label} |"
        )
    lines.append("")
    return lines
