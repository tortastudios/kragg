"""Resolution of the target project's Python environment.

kragg itself may be installed globally (pipx, ``uv tool install``) while the
project under check has its own virtual environment. Environment-dependent
tools (pytest, mypy, pip-audit, deptry) must run on the project interpreter,
never on kragg's own, so they see the project's packages.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from kragg.models import CompletedCommand
from kragg.runner import run_command

ENV_VAR = "KRAGG_PROJECT_PYTHON"

PROJECT_MODULES: tuple[str, ...] = (
    "pytest",
    "pytest_cov",
    "mypy",
    "pip_audit",
    "deptry",
)

_REMEDIATIONS: dict[str, str] = {
    "pytest": "uv add --dev pytest pytest-cov",
    "pytest_cov": "uv add --dev pytest-cov",
    "mypy": "uv add --dev mypy",
    "pip_audit": "uv add --dev pip-audit",
    "deptry": "uv add --dev deptry",
}

_NO_MODULE = re.compile(r"No module named '?([A-Za-z0-9_]+)")


@dataclass(frozen=True)
class ProjectEnvironment:
    """Resolved interpreter for the target project's environment."""

    root: Path
    python: Path | None
    source: str

    @property
    def found(self) -> bool:
        return self.source != "missing"

    def command(self, *args: str) -> list[str]:
        if self.python is not None:
            return [str(self.python), *args]
        return ["uv", "run", "--project", str(self.root), "python", *args]

    def module_command(self, module: str, *args: str) -> list[str]:
        return self.command("-m", module, *args)

    def script_command(self, name: str, *args: str) -> list[str]:
        """Invoke a console-script entry point in the project environment.

        Some tools (e.g. cosmic-ray) are not runnable via ``python -m``; they
        ship only a console script in the environment's bin directory.
        """
        if self.python is not None:
            return [str(self.python.parent / name), *args]
        return ["uv", "run", "--project", str(self.root), name, *args]

    def describe(self) -> str:
        if self.python is not None:
            return f"{self.python} (via {self.source})"
        if self.source == "uv":
            return f"uv run --project {self.root} python (via uv)"
        return "missing"


def resolve_project_environment(root: Path) -> ProjectEnvironment:
    """Resolve the project interpreter, never falling back to kragg's own."""
    override = os.environ.get(ENV_VAR)
    if override:
        path = Path(override)
        if not path.exists():
            raise RuntimeError(f"{ENV_VAR} points to a missing path: {override}")
        return ProjectEnvironment(root=root, python=path, source=ENV_VAR)

    venv = venv_python(root / ".venv")
    if venv.exists():
        return ProjectEnvironment(root=root, python=venv, source=".venv")

    active = os.environ.get("VIRTUAL_ENV")
    if active:
        candidate = Path(active)
        python = venv_python(candidate)
        if python.exists() and not _is_foreign_environment(candidate, root):
            return ProjectEnvironment(root=root, python=python, source="VIRTUAL_ENV")

    if shutil.which("uv") is not None:
        return ProjectEnvironment(root=root, python=None, source="uv")

    return ProjectEnvironment(root=root, python=None, source="missing")


def _is_foreign_environment(venv: Path, root: Path) -> bool:
    """Return True when a venv is kragg's own environment outside the project."""
    prefix = Path(sys.prefix).resolve()
    if prefix != venv.resolve():
        return False
    return not prefix.is_relative_to(root.resolve())


def venv_python(venv: Path) -> Path:
    """Return the interpreter path inside a virtual environment."""
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def missing_module(result: CompletedCommand) -> str | None:
    """Detect a module missing from the environment a command ran in."""
    match = _NO_MODULE.search(result.stderr) or _NO_MODULE.search(result.stdout)
    if match:
        return match.group(1)
    if "unrecognized arguments: --cov" in result.output:
        return "pytest_cov"
    return None


def remediation(module: str) -> str:
    """Return the exact command that installs a missing project tool."""
    command = _REMEDIATIONS.get(module, f"uv add --dev {module.replace('_', '-')}")
    return f"Fix: {command} (or run `uv sync` if already declared)"


def missing_interpreter_message(root: Path) -> str:
    return (
        f"No project interpreter found for {root}.\n"
        f"Fix: uv sync (or set {ENV_VAR}=/path/to/python)"
    )


def probe_modules(
    env: ProjectEnvironment,
    modules: tuple[str, ...],
) -> dict[str, bool] | None:
    """Check which modules import in the project environment (doctor only)."""
    if not env.found:
        return None
    script = (
        "import importlib.util, sys\n"
        "for name in sys.argv[1:]:\n"
        "    spec = importlib.util.find_spec(name)\n"
        "    print(name + '=' + ('1' if spec else '0'))\n"
    )
    result = run_command("probe", env.command("-c", script, *modules), env.root)
    if not result.passed:
        return None
    found: dict[str, bool] = {}
    for line in result.stdout.splitlines():
        name, _, flag = line.partition("=")
        if name in modules:
            found[name] = flag == "1"
    return found if found else None
