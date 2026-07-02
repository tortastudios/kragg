"""Package-name derivation and import-shadowing guard for `kragg new`.

A scaffolded package that reuses a stdlib or widely-installed top-level
import name shadows the installed package at import time — an error no
gate can point at, so `kragg new` refuses such names up front.
"""

from __future__ import annotations

import re
import sys

# Top-level import names of widely-installed distributions.
COMMON_DISTRIBUTIONS: frozenset[str] = frozenset(
    {
        "anthropic",
        "boto3",
        "celery",
        "click",
        "django",
        "fastapi",
        "fastmcp",
        "flask",
        "google",
        "httpx",
        "kragg",
        "mcp",
        "mypy",
        "numpy",
        "openai",
        "pandas",
        "pydantic",
        "pytest",
        "redis",
        "requests",
        "rich",
        "ruff",
        "sqlalchemy",
        "starlette",
        "typer",
        "uvicorn",
    }
)


def normalize_package_name(name: str) -> str:
    """Return a valid Python package name derived from a project name."""
    normalized = re.sub(r"\W+", "_", name).strip("_").lower()
    if not normalized:
        return "app"
    if normalized[0].isdigit():
        return f"app_{normalized}"
    return normalized


def shadow_conflict(package: str) -> str | None:
    """Return what an import package name would shadow, or None if safe."""
    if package in sys.stdlib_module_names:
        return f"the Python standard library module '{package}'"
    if package in COMMON_DISTRIBUTIONS:
        return f"the '{package}' package on PyPI"
    return None


def shadow_refusal(package: str, conflict: str) -> str:
    """Return the copy-pasteable refusal message for a shadowing package."""
    return (
        f"package name '{package}' would shadow {conflict}; imports of "
        f"{package}.* would resolve to this project and break at import time.\n"
        "Fix: choose a different project name, pass --package <importable-name> "
        "to keep this project name, or pass --allow-shadowing to proceed anyway."
    )
