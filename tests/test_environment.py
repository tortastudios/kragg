import sys
from pathlib import Path
from typing import Any

import pytest

from crag import environment
from crag.environment import (
    resolve_project_environment,
    venv_python,
)
from crag.models import CompletedCommand


def _make_python(venv: Path) -> Path:
    python = venv_python(venv)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("")
    return python


def _clear_env(monkeypatch: Any) -> None:
    monkeypatch.delenv(environment.ENV_VAR, raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)


def test_resolve_prefers_env_var(tmp_path: Path, monkeypatch: Any) -> None:
    _clear_env(monkeypatch)
    python = _make_python(tmp_path / "custom")
    monkeypatch.setenv(environment.ENV_VAR, str(python))

    env = resolve_project_environment(tmp_path)

    assert env.source == environment.ENV_VAR
    assert env.python == python


def test_resolve_env_var_missing_path_errors(tmp_path: Path, monkeypatch: Any) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(environment.ENV_VAR, str(tmp_path / "missing"))

    with pytest.raises(RuntimeError):
        resolve_project_environment(tmp_path)


def test_resolve_finds_dot_venv(tmp_path: Path, monkeypatch: Any) -> None:
    _clear_env(monkeypatch)
    python = _make_python(tmp_path / ".venv")

    env = resolve_project_environment(tmp_path)

    assert env.source == ".venv"
    assert env.python == python
    assert env.module_command("mypy", "src") == [str(python), "-m", "mypy", "src"]


def test_resolve_uses_virtual_env(tmp_path: Path, monkeypatch: Any) -> None:
    _clear_env(monkeypatch)
    other = tmp_path / "elsewhere" / "venv"
    _make_python(other)
    monkeypatch.setenv("VIRTUAL_ENV", str(other))

    env = resolve_project_environment(tmp_path / "project")

    assert env.source == "VIRTUAL_ENV"


def test_resolve_skips_crag_own_environment(tmp_path: Path, monkeypatch: Any) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    monkeypatch.setattr("crag.environment.shutil.which", lambda _: None)

    env = resolve_project_environment(tmp_path)

    assert env.source == "missing"
    assert not env.found


def test_resolve_falls_back_to_uv(tmp_path: Path, monkeypatch: Any) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setattr("crag.environment.shutil.which", lambda _: "/usr/bin/uv")

    env = resolve_project_environment(tmp_path)

    assert env.source == "uv"
    assert env.module_command("pytest", "-q") == [
        "uv",
        "run",
        "--project",
        str(tmp_path),
        "python",
        "-m",
        "pytest",
        "-q",
    ]


def _completed(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 1,
) -> CompletedCommand:
    return CompletedCommand(
        name="x",
        command=("x",),
        cwd=Path("."),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_missing_module_parses_stderr() -> None:
    result = _completed(stderr="/x/python: No module named pytest")
    assert environment.missing_module(result) == "pytest"

    quoted = _completed(stderr="ModuleNotFoundError: No module named 'mypy'")
    assert environment.missing_module(quoted) == "mypy"

    ordinary = _completed(stderr="assert 1 == 2")
    assert environment.missing_module(ordinary) is None


def test_missing_module_detects_pytest_cov() -> None:
    result = _completed(stderr="pytest: error: unrecognized arguments: --cov=src")
    assert environment.missing_module(result) == "pytest_cov"


def test_remediation_includes_uv_add() -> None:
    assert "uv add --dev pytest pytest-cov" in environment.remediation("pytest")
    assert "uv add --dev pip-audit" in environment.remediation("pip_audit")
    assert "uv add --dev some-tool" in environment.remediation("some_tool")
