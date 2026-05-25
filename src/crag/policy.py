from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class CragPolicy:
    """Configuration for the active guardrails policy pack."""

    profile: str = "strict-ai-python"
    source_paths: tuple[str, ...] = ("src",)
    test_paths: tuple[str, ...] = ("tests",)
    coverage_fail_under: int = 80
    type_max_nesting_depth: int = 2
    type_max_length: int = 40

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], asdict(self))


def load_policy(root: Path) -> CragPolicy:
    """Load policy settings from pyproject.toml, falling back to defaults."""
    table = _load_crag_table(root)
    default = CragPolicy()
    return CragPolicy(
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
    )


def _load_crag_table(root: Path) -> dict[str, object]:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return {}

    data = tomllib.loads(pyproject.read_text())
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return {}

    crag = tool.get("crag")
    if not isinstance(crag, dict):
        return {}

    return cast(dict[str, object], crag)


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
