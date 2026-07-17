import json
import sys
from pathlib import Path
from typing import Any

from kragg import environment
from kragg.cli import main
from kragg.environment import venv_python
from kragg.models import CompletedCommand


def test_policy_show_returns_success(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["policy", "show"]) == 0


def test_no_command_exits_with_usage_code(capsys: Any) -> None:
    assert main([]) == 2
    capsys.readouterr()


def test_doctor_fails_without_project_files(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(environment.ENV_VAR, raising=False)

    assert main(["doctor"]) == 1


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n\n[tool.mypy]\nstrict = true\n'
    )
    package = tmp_path / "src" / "demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Demo."""\n')
    (tmp_path / "tests").mkdir()
    python = venv_python(tmp_path / ".venv")
    python.parent.mkdir(parents=True)
    python.write_text("")
    return python


class _FakeRunner:
    """Records commands and returns scripted results."""

    def __init__(self) -> None:
        self.commands: dict[str, list[str]] = {}
        self.failures: dict[str, CompletedCommand] = {}

    def __call__(self, name: str, command: Any, cwd: Path) -> CompletedCommand:
        self.commands[name] = list(command)
        if name in self.failures:
            return self.failures[name]
        return CompletedCommand(
            name=name,
            command=tuple(command),
            cwd=cwd,
            returncode=0,
            stdout="",
            stderr="",
        )


def _setup_check(tmp_path: Path, monkeypatch: Any) -> _FakeRunner:
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(environment.ENV_VAR, raising=False)
    runner = _FakeRunner()
    monkeypatch.setattr("kragg.catalog.run_command", runner)
    monkeypatch.setattr("kragg.catalog.secrets.scan_target", lambda root, target: {})
    return runner


def test_check_runs_env_dependent_tools_on_project_python(
    tmp_path: Path, monkeypatch: Any
) -> None:
    runner = _setup_check(tmp_path, monkeypatch)
    project_python = str(venv_python(tmp_path / ".venv"))

    assert main(["check"]) == 0

    assert runner.commands["mypy"][0] == project_python
    assert runner.commands["pytest-coverage"][0] == project_python
    assert runner.commands["pip-audit"][0] == project_python
    assert runner.commands["ruff"][0] == sys.executable
    assert runner.commands["radon-cc"][0] == sys.executable


def test_check_missing_pytest_prints_remediation(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    runner = _setup_check(tmp_path, monkeypatch)
    runner.failures["pytest-coverage"] = CompletedCommand(
        name="pytest-coverage",
        command=(),
        cwd=tmp_path,
        returncode=1,
        stdout="",
        stderr="/x/python: No module named pytest",
    )

    assert main(["check"]) == 3

    out = capsys.readouterr().out
    assert "uv add --dev pytest pytest-cov" in out


def test_user_code_import_error_is_a_test_failure_not_env_error(
    tmp_path: Path, monkeypatch: Any
) -> None:
    runner = _setup_check(tmp_path, monkeypatch)
    runner.failures["pytest-coverage"] = CompletedCommand(
        name="pytest-coverage",
        command=(),
        cwd=tmp_path,
        returncode=1,
        stdout="ModuleNotFoundError: No module named 'demo'",
        stderr="",
    )

    assert main(["check"]) == 1


def test_check_reports_all_static_failures_in_one_run(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    runner = _setup_check(tmp_path, monkeypatch)
    runner.failures["ruff"] = CompletedCommand(
        name="ruff",
        command=(),
        cwd=tmp_path,
        returncode=1,
        stdout=json.dumps(
            [
                {
                    "filename": "src/demo/__init__.py",
                    "location": {"row": 1, "column": 1},
                    "code": "F401",
                    "message": "unused import",
                    "fix": None,
                }
            ]
        ),
        stderr="",
    )
    runner.failures["mypy"] = CompletedCommand(
        name="mypy",
        command=(),
        cwd=tmp_path,
        returncode=1,
        stdout="src/demo/__init__.py:1: error: Bad type",
        stderr="",
    )

    assert main(["check"]) == 1

    out = capsys.readouterr().out
    assert "[FAIL] ruff" in out
    assert "[FAIL] mypy" in out
    assert "[SKIP] pytest-coverage — static gates failed" in out


def test_check_json_output_is_one_document(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    _setup_check(tmp_path, monkeypatch)

    assert main(["check", "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["passed"] is True
    names = [gate["name"] for gate in payload["gates"]]
    assert "ruff" in names
    assert "pytest-coverage" in names


def test_check_without_project_interpreter_exits_3(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    runner = _setup_check(tmp_path, monkeypatch)
    del runner  # gates still run; env-dependent ones error
    venv_python(tmp_path / ".venv").unlink()
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr("kragg.environment.shutil.which", lambda _: None)

    assert main(["check"]) == 3

    out = capsys.readouterr().out
    assert "No project interpreter" in out


def test_check_changed_outside_git_repo_exits_3(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _setup_check(tmp_path, monkeypatch)
    monkeypatch.setattr("kragg.commands.changed_python_files", lambda *a: None)

    assert main(["check", "--changed"]) == 3


def test_check_changed_with_no_files_is_a_cheap_pass(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    _setup_check(tmp_path, monkeypatch)
    monkeypatch.setattr("kragg.commands.changed_python_files", lambda *a: [])

    assert main(["check", "--changed"]) == 0
    assert "no changed Python files" in capsys.readouterr().out


def test_check_writes_journal_and_status_reads_it(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    _setup_check(tmp_path, monkeypatch)

    assert main(["check"]) == 0
    capsys.readouterr()

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "last run: PASS" in out


def test_status_without_journal(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["status"]) == 0
    assert "no recorded runs" in capsys.readouterr().out


def test_new_scaffolds_without_sync(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["new", "demo", "--no-sync"]) == 0

    out = capsys.readouterr().out
    assert "Next steps:" in out
    assert (tmp_path / "demo" / "AGENTS.md").exists()


def test_new_refuses_non_empty_target(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "keep.txt").write_text("x")

    assert main(["new", "demo", "--no-sync"]) == 1


def test_new_refuses_shadowing_name(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["new", "mcp", "--kind", "mcp", "--no-sync"]) == 1

    err = capsys.readouterr().err
    assert "--package" in err
    assert "--allow-shadowing" in err
    assert not (tmp_path / "mcp").exists()


def test_new_allow_shadowing_warns_and_proceeds(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["new", "mcp", "--allow-shadowing", "--no-sync"]) == 0

    assert "warning: package 'mcp' shadows" in capsys.readouterr().err
    assert (tmp_path / "mcp" / "src" / "mcp").is_dir()


def test_new_package_flag_names_the_import_package(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["new", "mcp", "--package", "brain-mcp", "--no-sync"]) == 0

    assert (tmp_path / "mcp" / "src" / "brain_mcp").is_dir()


def test_init_adds_kragg_files(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "existing"\n')

    assert main(["init", "."]) == 0
    assert (tmp_path / "AGENTS.md").exists()


def test_fix_runs_format_and_safe_fixes(tmp_path: Path, monkeypatch: Any) -> None:
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = _FakeRunner()
    monkeypatch.setattr("kragg.commands.run_command", runner)

    assert main(["fix"]) == 0

    assert runner.commands["ruff format"][:3] == [sys.executable, "-m", "ruff"]
    assert "--fix" in runner.commands["ruff fix"]


def test_security_json_reports_gates(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    _setup_check(tmp_path, monkeypatch)

    assert main(["security", "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    names = [gate["name"] for gate in payload["gates"]]
    assert names == [
        "forbidden-calls",
        "secret-default",
        "bandit",
        "detect-secrets",
        "pip-audit",
    ]


def test_doctor_reports_missing_project_tools(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(environment.ENV_VAR, raising=False)
    probed = {name: name != "mypy" for name in environment.PROJECT_MODULES}
    monkeypatch.setattr("kragg.environment.probe_modules", lambda env, modules: probed)

    assert main(["doctor"]) == 1

    out = capsys.readouterr().out
    assert "project interpreter:" in out
    assert "mypy: MISSING -> Fix: uv add --dev mypy" in out
