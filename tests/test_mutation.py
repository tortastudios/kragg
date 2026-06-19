import json
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from kragg.environment import ProjectEnvironment
from kragg.models import CompletedCommand
from kragg.mutation import (
    Survivor,
    build_config,
    cosmic_ray_available,
    diff_summary,
    drop_annotation_mutants,
    filter_baselined,
    format_test_command,
    load_baseline,
    parse_survivors,
    render_survivors,
    run_mutation,
    select_targets,
    survivor_violation,
    write_baseline,
)
from kragg.policy import KraggPolicy

POLICY = KraggPolicy()

_DIFF = (
    "--- mutation diff ---\n--- am.py\n+++ bm.py\n@@ -1,3 +1,3 @@\n"
    " def vital(n):\n-    if n > 0:\n+    if n >= 0:\n"
)


def _dump_line(outcome: str) -> str:
    item = {
        "job_id": "j",
        "mutations": [
            {
                "module_path": "src/app/core.py",
                "operator_name": "core/ReplaceComparisonOperator_Gt_GtE",
                "occurrence": 1,
                "start_pos": [2, 7],
                "end_pos": [2, 8],
                "operator_args": {},
                "definition_name": "vital",
            }
        ],
    }
    result = {
        "worker_outcome": "normal",
        "output": "1 passed",
        "test_outcome": outcome,
        "diff": _DIFF,
    }
    return json.dumps([item, result])


_DUMP = "\n".join(
    [
        _dump_line("survived"),
        _dump_line("killed"),
        json.dumps([{"job_id": "k", "mutations": []}, None]),
    ]
)


def _fake_env(tmp_path: Path) -> ProjectEnvironment:
    python = tmp_path / ".venv" / "bin" / "python"
    return ProjectEnvironment(root=tmp_path, python=python, source=".venv")


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed git commands in a test fixture.
        ["git", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, criticality: list[dict[str, object]]) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    pkg = tmp_path / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text("def vital() -> int:\n    return 1\n")
    (pkg / "util.py").write_text("def helper() -> int:\n    return 2\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    kragg_dir = tmp_path / ".kragg"
    kragg_dir.mkdir()
    (kragg_dir / "criticality.json").write_text(json.dumps(criticality))


def _two_criticals() -> list[dict[str, object]]:
    return [
        {"name": "app.core.vital", "is_critical": True, "fan_in": 5},
        {"name": "app.util.helper", "is_critical": True, "fan_in": 4},
    ]


def test_select_targets_changed_intersect_critical(tmp_path: Path) -> None:
    _repo(tmp_path, _two_criticals())
    (tmp_path / "src" / "app" / "core.py").write_text(
        "def vital() -> int:\n    return 9\n"
    )

    assert select_targets(tmp_path, POLICY, None, False) == ("src/app/core.py",)


def test_select_targets_clean_tree_is_empty(tmp_path: Path) -> None:
    _repo(tmp_path, _two_criticals())

    assert select_targets(tmp_path, POLICY, None, False) == ()


def test_select_targets_all_returns_all_critical_files(tmp_path: Path) -> None:
    _repo(tmp_path, _two_criticals())

    targets = select_targets(tmp_path, POLICY, None, True)

    assert set(targets) == {"src/app/core.py", "src/app/util.py"}


def test_select_targets_non_git_returns_none(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text("def vital() -> int:\n    return 1\n")
    kragg_dir = tmp_path / ".kragg"
    kragg_dir.mkdir()
    (kragg_dir / "criticality.json").write_text(
        json.dumps([{"name": "app.core.vital", "is_critical": True, "fan_in": 5}])
    )

    assert select_targets(tmp_path, POLICY, None, False) is None


def test_build_config_is_valid_toml() -> None:
    config = build_config("src/app/core.py", "py -m pytest -x -q tests", 25.0)

    data = tomllib.loads(config)

    assert data["cosmic-ray"]["module-path"] == "src/app/core.py"
    assert data["cosmic-ray"]["timeout"] == 25.0
    assert data["cosmic-ray"]["test-command"] == "py -m pytest -x -q tests"
    assert data["cosmic-ray"]["distributor"]["name"] == "local"


def test_format_test_command_joins_safely() -> None:
    command = format_test_command(("/venv/bin/python",), ("tests",))

    assert command == "/venv/bin/python -m pytest -x -q tests"


def test_parse_survivors_keeps_only_survived() -> None:
    survivors = parse_survivors(_DUMP)

    assert len(survivors) == 1
    survivor = survivors[0]
    assert survivor.file == "src/app/core.py"
    assert survivor.line == 2
    assert survivor.function == "vital"
    assert survivor.occurrence == 1
    assert "ReplaceComparisonOperator_Gt_GtE" in survivor.operator


def test_parse_survivors_ignores_malformed_lines() -> None:
    assert parse_survivors("not json\n[]\n{}\n\n") == ()


def test_survivor_signature_is_session_independent() -> None:
    survivor = Survivor("f.py", 2, 0, "vital", "core/Op", 3, "")

    assert survivor.signature() == "f.py::core/Op::3"


def test_diff_summary_extracts_old_and_new() -> None:
    assert diff_summary(_DIFF) == "if n > 0: -> if n >= 0:"


def test_survivor_violation_has_location_and_hint() -> None:
    violation = survivor_violation(parse_survivors(_DUMP)[0])

    assert violation.code == "mutant"
    assert violation.file == "src/app/core.py"
    assert violation.line == 2
    assert violation.fix_hint is not None
    assert "vital" in violation.fix_hint


def test_render_survivors_empty_message() -> None:
    assert render_survivors(()) == ["no surviving mutants"]


def test_render_survivors_lists_each(tmp_path: Path) -> None:
    lines = render_survivors(parse_survivors(_DUMP))

    assert "1 surviving mutants in 1 files" in lines[0]
    assert any("src/app/core.py:2" in line for line in lines)


def test_run_mutation_collects_survivors(tmp_path: Path, monkeypatch: Any) -> None:
    def fake(name: str, command: list[str], cwd: Path) -> CompletedCommand:
        out = _DUMP if "dump" in command else ""
        return CompletedCommand(name, tuple(command), cwd, 0, out, "")

    monkeypatch.setattr("kragg.mutation.run_command", fake)

    report = run_mutation(tmp_path, _fake_env(tmp_path), POLICY, ("src/app/core.py",))

    assert report.error is None
    assert report.files_tested == 1
    assert len(report.survivors) == 1


def test_run_mutation_reports_exec_failure(tmp_path: Path, monkeypatch: Any) -> None:
    def fake(name: str, command: list[str], cwd: Path) -> CompletedCommand:
        code = 1 if "exec" in command else 0
        return CompletedCommand(name, tuple(command), cwd, code, "", "boom")

    monkeypatch.setattr("kragg.mutation.run_command", fake)

    report = run_mutation(tmp_path, _fake_env(tmp_path), POLICY, ("src/app/core.py",))

    assert report.error is not None
    assert "exec failed" in report.error


def test_drop_annotation_mutants_keeps_defaults_drops_unions(tmp_path: Path) -> None:
    source = tmp_path / "m.py"
    code = (
        "from __future__ import annotations\n\n\n"
        "def f(x: int = 80) -> str | None:\n"
        "    return None\n"
    )
    source.write_text(code)
    signature = code.splitlines()[3]
    in_annotation = Survivor("m.py", 4, signature.index("|"), "f", "op", 0, "")
    on_default = Survivor("m.py", 4, signature.index("80"), "f", "op", 1, "")

    kept = drop_annotation_mutants((in_annotation, on_default), source)

    assert on_default in kept
    assert in_annotation not in kept


def test_load_baseline_missing_is_empty(tmp_path: Path) -> None:
    assert load_baseline(tmp_path) == set()


def test_baseline_round_trip(tmp_path: Path) -> None:
    survivors = parse_survivors(_DUMP)

    count = write_baseline(tmp_path, survivors)

    assert count == 1
    assert survivors[0].signature() in load_baseline(tmp_path)


def test_filter_baselined_drops_known_signatures(tmp_path: Path) -> None:
    survivors = parse_survivors(_DUMP)
    baseline = {survivors[0].signature()}

    assert filter_baselined(survivors, baseline) == ()
    assert filter_baselined(survivors, set()) == survivors


def test_cosmic_ray_available_checks_bin(tmp_path: Path) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    env = ProjectEnvironment(root=tmp_path, python=python, source=".venv")

    assert cosmic_ray_available(env) is False

    (python.parent / "cosmic-ray").write_text("")
    assert cosmic_ray_available(env) is True
