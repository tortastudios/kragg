from __future__ import annotations

import re
from pathlib import Path

from crag import templates


def normalize_package_name(name: str) -> str:
    """Return a valid Python package name derived from a project name."""
    normalized = re.sub(r"\W+", "_", name).strip("_").lower()
    if not normalized:
        return "app"
    if normalized[0].isdigit():
        return f"app_{normalized}"
    return normalized


def create_new_project(
    root: Path,
    project_name: str,
    kind: str = "cli",
) -> list[Path]:
    """Create a new crag-managed Python project with a layered layout."""
    if kind not in templates.KINDS:
        raise ValueError(f"unknown kind: {kind}")
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Target directory is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    package_name = normalize_package_name(project_name)
    files = _guardrail_files(project_name, kind)
    files.update(templates.kind_files(kind, package_name, project_name))
    return _write_files(root, files, overwrite=True)


def initialize_project(root: Path) -> list[Path]:
    """Add crag guardrail files to an existing project (no skeleton code)."""
    root.mkdir(parents=True, exist_ok=True)
    project_name = root.name
    files = _guardrail_files(project_name, kind="cli")
    del files["pyproject.toml"]
    written = _write_files(root, files, overwrite=False)
    _ensure_pyproject_config(root, project_name)
    return written


def generate_module(root: Path, name: str) -> list[Path]:
    """Generate service/domain/test slots for a new module."""
    package = _detect_package(root)
    module = normalize_package_name(name)
    files = templates.module_files(package, module)
    written = _write_files(root, files, overwrite=False)
    if not written:
        raise FileExistsError(f"module '{module}' already exists")
    return written


def _detect_package(root: Path) -> str:
    src = root / "src"
    if not src.is_dir():
        raise RuntimeError("no src/ directory found; run from the project root")
    packages = sorted(
        path.name for path in src.iterdir() if (path / "__init__.py").exists()
    )
    if len(packages) != 1:
        raise RuntimeError(
            f"expected exactly one package under src/, found: {packages or 'none'}"
        )
    return packages[0]


def _guardrail_files(project_name: str, kind: str) -> dict[str, str]:
    return {
        "README.md": _readme(project_name),
        ".python-version": "3.12\n",
        ".gitignore": GITIGNORE,
        "pyproject.toml": _pyproject(project_name, kind),
        "Makefile": MAKEFILE,
        ".pre-commit-config.yaml": PRE_COMMIT,
        ".github/workflows/quality.yml": GITHUB_ACTIONS,
        ".claude/settings.json": CLAUDE_SETTINGS,
        ".gemini/settings.json": GEMINI_SETTINGS,
        "AGENTS.md": AGENTS_MD,
        "CLAUDE.md": CLAUDE_MD,
        "CRITICALITY.md": CRITICALITY_MD,
        "docs/type-complexity.md": TYPE_COMPLEXITY_DOC,
    }


def _write_files(
    root: Path,
    files: dict[str, str],
    overwrite: bool,
) -> list[Path]:
    written: list[Path] = []
    for relative, content in files.items():
        path = root / relative
        if path.exists() and not overwrite:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        written.append(path)
    return written


def _ensure_pyproject_config(root: Path, project_name: str) -> None:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(_pyproject(project_name, kind=None))
        return

    content = pyproject.read_text()
    additions: list[str] = []
    if "[tool.crag]" not in content:
        additions.append(TOOL_CRAG)
    if "[dependency-groups]" not in content and "crag" not in content:
        additions.append(
            "\n[dependency-groups]\n"
            "dev = [\n"
            '    "crag>=0.1.0",\n'
            '    "pytest>=9.0.2",\n'
            '    "pytest-cov>=7.0.0",\n'
            '    "mypy>=1.19.1",\n'
            "]\n"
        )
    if additions:
        pyproject.write_text(content.rstrip() + "\n" + "".join(additions))


def _readme(project_name: str) -> str:
    return f"# {project_name}\n\nGenerated with `crag`.\n"


def _pyproject(project_name: str, kind: str | None) -> str:
    package_name = normalize_package_name(project_name)
    dependencies = _toml_list(templates.kind_dependencies(kind) if kind else [])
    dev_extras = templates.kind_dev_extras(kind) if kind else []
    dev = _toml_list(
        [
            '"crag>=0.1.0"',
            '"pytest>=9.0.2"',
            '"pytest-cov>=7.0.0"',
            '"mypy>=1.19.1"',
            *dev_extras,
        ]
    )
    scripts = templates.kind_scripts(kind, project_name, package_name) if kind else ""
    layers = (
        f'layers = ["{package_name}.entrypoints", "{package_name}.services", '
        f'"{package_name}.domain"]\n'
        if kind
        else ""
    )
    return f"""[project]
name = "{project_name}"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.12"
dependencies = {dependencies}
{scripts}
[dependency-groups]
dev = {dev}

[tool.crag]
profile = "strict-ai-python"
source_paths = ["src"]
test_paths = ["tests"]
coverage_fail_under = 80
type_max_nesting_depth = 2
type_max_length = 40
{layers}
[tool.pytest.ini_options]
addopts = "--cov=src --cov-report=term-missing --cov-fail-under=80 -q"
testpaths = ["tests"]

[tool.coverage.report]
exclude_also = ["if __name__ == .__main__.:"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]
"""


def _toml_list(items: list[str]) -> str:
    if not items:
        return "[]"
    body = "".join(f"    {item},\n" for item in items)
    return f"[\n{body}]"


TOOL_CRAG = """
[tool.crag]
profile = "strict-ai-python"
source_paths = ["src"]
test_paths = ["tests"]
coverage_fail_under = 80
type_max_nesting_depth = 2
type_max_length = 40
"""

GITIGNORE = """# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/

# testing
.pytest_cache/
.coverage
htmlcov/
coverage.xml

# mypy
.mypy_cache/

# ruff
.ruff_cache/

# crag run journal
.crag/

# env
.env
.env.*
!.env.example

# OS
.DS_Store
"""

MAKEFILE = """FILE ?=

.PHONY: check fix audit security criticality doctor

check:
	uv run crag check $(if $(FILE),--file $(FILE),)

fix:
	uv run crag fix $(if $(FILE),--file $(FILE),)

security:
	uv run crag security $(if $(FILE),--file $(FILE),)

audit:
	uv run crag audit

criticality:
	uv run crag criticality --write

doctor:
	uv run crag doctor
"""

PRE_COMMIT = """repos:
  - repo: local
    hooks:
      - id: crag-check
        name: crag check
        entry: uv run crag check
        language: system
        types: [python]
        pass_filenames: false
"""

GITHUB_ACTIONS = """name: Quality Gates

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          version: "latest"
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: uv sync
      - name: Run crag
        run: uv run crag check
"""

CLAUDE_SETTINGS = """{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "uv run crag hook claude"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run crag hook claude"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run crag hook claude"
          }
        ]
      }
    ]
  }
}
"""

GEMINI_SETTINGS = """{
  "contextFileName": "AGENTS.md"
}
"""

AGENTS_MD = """# Agent Contract

This project is guarded by `crag`. Gates are enforced, not advisory: if a gate
fails, fix the failure before moving to unrelated work.

## Commands

| When | Command |
| --- | --- |
| After editing Python files (inner loop) | `uv run crag check --changed` |
| Before claiming a task is done | `uv run crag check` |
| Auto-fix formatting and safe lint | `uv run crag fix` |
| Machine-readable results | `uv run crag check --format json` |
| What failed last run (without re-running) | `uv run crag status` |
| Environment problems | `uv run crag doctor` |

## Exit codes

- `0` all gates passed
- `1` gate failures — fix the reported `file:line` violations
- `2` usage error — fix the command invocation
- `3` environment broken — run `uv run crag doctor` and apply the printed fix

## Layout

Layered architecture, enforced by the `boundaries` gate (a lower layer may
never import a higher one):

- `src/<pkg>/entrypoints/` — CLI/HTTP/worker surfaces; thin, no business logic
- `src/<pkg>/services/` — orchestration; the only layer entrypoints call
- `src/<pkg>/domain/` — pure data and rules; imports nothing above it

Create new modules with `uv run crag gen module <name>` — it generates the
service, domain, and test slots so everything has exactly one place.

## Quality rules

- Run gates through the project environment (`uv run crag ...`), never globally.
- Before editing functions listed in `CRITICALITY.md`, use extra scrutiny: full
  input and return types, a contract docstring, and tests for changed behavior.
- Prefer early returns over nested conditionals.
- Keep functions short and typed.
- Extract named dataclasses, TypedDicts, or aliases for complex annotations.
- Never hardcode credentials.
- Never suppress security or typing findings without an explicit reason.
"""

CLAUDE_MD = """Follow the rules in AGENTS.md. It is the canonical agent contract
for this repository.
"""

CRITICALITY_MD = """# Critical Functions

> Generated by `crag criticality --write`.

No critical functions have been analyzed yet.
"""

TYPE_COMPLEXITY_DOC = """# Type Annotation Complexity

`crag` limits type annotation nesting and length so data shapes get names.

Use:

- `@dataclass` for domain data you own.
- `TypedDict` for external dict or JSON data.
- `TypeAlias` for shallow primitive shapes used locally.
"""
