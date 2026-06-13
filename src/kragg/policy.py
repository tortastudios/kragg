from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class KraggPolicy:
    """Configuration for the active guardrails policy pack."""

    profile: str = "strict-ai-python"
    source_paths: tuple[str, ...] = ("src",)
    test_paths: tuple[str, ...] = ("tests",)
    coverage_fail_under: int = 80
    type_max_nesting_depth: int = 2
    type_max_length: int = 40
    max_violations_per_gate: int = 25
    layers: tuple[str, ...] = ()
    max_file_lines: int = 500
    max_public_symbols: int = 20

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], asdict(self))


def load_policy(root: Path) -> KraggPolicy:
    """Load policy from kragg.toml, then pyproject [tool.kragg], then defaults."""
    table = _load_kragg_table(root)
    default = KraggPolicy()
    return KraggPolicy(
        profile=_get_str(table, "profile", default.profile),
        source_paths=_get_str_tuple(table, "source_paths", default.source_paths),
        test_paths=_get_str_tuple(table, "test_paths", default.test_paths),
        coverage_fail_under=_get_int(
            table,
            "coverage_fail_under",
            default.coverage_fail_under,
        ),
        type_max_nesting_depth=_get_int(
            table,
            "type_max_nesting_depth",
            default.type_max_nesting_depth,
        ),
        type_max_length=_get_int(table, "type_max_length", default.type_max_length),
        max_violations_per_gate=_get_int(
            table,
            "max_violations_per_gate",
            default.max_violations_per_gate,
        ),
        layers=_get_str_tuple(table, "layers", default.layers),
        max_file_lines=_get_int(table, "max_file_lines", default.max_file_lines),
        max_public_symbols=_get_int(
            table,
            "max_public_symbols",
            default.max_public_symbols,
        ),
    )


def _load_kragg_table(root: Path) -> dict[str, object]:
    standalone = root / "kragg.toml"
    if standalone.exists():
        return cast(dict[str, object], tomllib.loads(standalone.read_text()))

    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return {}

    data = tomllib.loads(pyproject.read_text())
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return {}

    kragg = tool.get("kragg")
    if not isinstance(kragg, dict):
        return {}

    return cast(dict[str, object], kragg)


def _get_str(table: dict[str, object], key: str, default: str) -> str:
    value = table.get(key)
    return value if isinstance(value, str) else default


def _get_int(table: dict[str, object], key: str, default: int) -> int:
    value = table.get(key)
    if isinstance(value, int):
        return value
    return default


def _get_str_tuple(
    table: dict[str, object],
    key: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value: Any = table.get(key)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return default
