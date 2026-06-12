import json
from pathlib import Path
from typing import Any

from crag.environment import venv_python
from crag.hooks import run_claude_hook
from crag.models import CompletedCommand


def _make_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    package = tmp_path / "src" / "demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Demo."""\n')
    (tmp_path / "tests").mkdir()
    python = venv_python(tmp_path / ".venv")
    python.parent.mkdir(parents=True)
    python.write_text("")


def _fake_runner(failures: dict[str, CompletedCommand]) -> Any:
    def run(name: str, command: Any, cwd: Path) -> CompletedCommand:
        if name in failures:
            return failures[name]
        return CompletedCommand(
            name=name,
            command=tuple(command),
            cwd=cwd,
            returncode=0,
            stdout="",
            stderr="",
        )

    return run


def _setup(
    tmp_path: Path, monkeypatch: Any, failures: dict[str, Any] | None = None
) -> None:
    _make_project(tmp_path)
    monkeypatch.delenv("CRAG_PROJECT_PYTHON", raising=False)
    monkeypatch.setattr("crag.check.run_command", _fake_runner(failures or {}))
    monkeypatch.setattr("crag.check.secrets.scan_target", lambda root, target: {})


def _ruff_failure(tmp_path: Path) -> CompletedCommand:
    return CompletedCommand(
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


def test_post_edit_ignores_non_python_files(tmp_path: Path, capsys: Any) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_input": {"file_path": str(tmp_path / "README.md")},
        }
    )

    assert run_claude_hook(payload, tmp_path) == 0
    assert capsys.readouterr().out == ""


def test_post_edit_passing_gates_stays_silent(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    _setup(tmp_path, monkeypatch)
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_input": {"file_path": str(tmp_path / "src" / "demo" / "__init__.py")},
        }
    )

    assert run_claude_hook(payload, tmp_path) == 0
    assert capsys.readouterr().out == ""


def test_post_edit_failure_emits_block_decision(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    _setup(tmp_path, monkeypatch, {"ruff": _ruff_failure(tmp_path)})
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_input": {"file_path": str(tmp_path / "src" / "demo" / "__init__.py")},
        }
    )

    assert run_claude_hook(payload, tmp_path) == 0

    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "F401" in decision["reason"]


def test_stop_blocks_when_full_check_fails(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    _setup(tmp_path, monkeypatch, {"ruff": _ruff_failure(tmp_path)})
    payload = json.dumps({"hook_event_name": "Stop"})

    assert run_claude_hook(payload, tmp_path) == 0

    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block"
    assert "crag check must pass" in decision["reason"]


def test_stop_honors_stop_hook_active(tmp_path: Path, capsys: Any) -> None:
    payload = json.dumps({"hook_event_name": "Stop", "stop_hook_active": True})

    assert run_claude_hook(payload, tmp_path) == 0
    assert capsys.readouterr().out == ""


def test_session_start_reports_status_and_critical_functions(
    tmp_path: Path, capsys: Any
) -> None:
    crag_dir = tmp_path / ".crag"
    crag_dir.mkdir()
    (crag_dir / "history.jsonl").write_text(
        json.dumps(
            {
                "passed": False,
                "command": "check",
                "mode": "full",
                "ts": "2026-06-12T00:00:00+00:00",
                "duration_ms": 1200,
                "gates": [
                    {
                        "name": "ruff",
                        "passed": False,
                        "skipped": False,
                        "duration_ms": 100,
                        "violation_count": 2,
                    }
                ],
            }
        )
        + "\n"
    )
    (crag_dir / "criticality.json").write_text(
        json.dumps(
            [
                {"name": "demo.core.run", "is_critical": True},
                {"name": "demo.core.minor", "is_critical": False},
            ]
        )
    )

    assert (
        run_claude_hook(json.dumps({"hook_event_name": "SessionStart"}), tmp_path) == 0
    )

    out = capsys.readouterr().out
    assert "last run: FAIL" in out
    assert "demo.core.run" in out
    assert "demo.core.minor" not in out


def test_invalid_stdin_fails_open(tmp_path: Path, capsys: Any) -> None:
    assert run_claude_hook("not json at all", tmp_path) == 0
