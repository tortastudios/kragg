from pathlib import Path
from typing import Any

from kragg.environment import ProjectEnvironment
from kragg.flaky import (
    FlakyGate,
    FlakyTest,
    aggregate_reruns,
    passive_flaky,
    render_passive,
    render_reruns,
    run_reruns,
)
from kragg.models import CompletedCommand
from kragg.policy import KraggPolicy


def _run(
    sha: str | None,
    gates: list[dict[str, Any]],
    dirty: bool = False,
) -> dict[str, Any]:
    return {"git_sha": sha, "gates": gates, "git_dirty": dirty}


def _gate(name: str, passed: bool, skipped: bool = False) -> dict[str, Any]:
    return {"name": name, "passed": passed, "skipped": skipped}


def test_passive_detects_same_sha_flip() -> None:
    runs = [
        _run("abc", [_gate("pytest", True)]),
        _run("abc", [_gate("pytest", False)]),
    ]

    flaky = passive_flaky(runs)

    assert len(flaky) == 1
    assert flaky[0].name == "pytest"
    assert flaky[0].sha == "abc"
    assert flaky[0].passed == 1
    assert flaky[0].failed == 1


def test_flip_across_different_shas_is_not_flaky() -> None:
    runs = [
        _run("abc", [_gate("pytest", True)]),
        _run("def", [_gate("pytest", False)]),
    ]

    assert passive_flaky(runs) == ()


def test_skipped_gates_are_ignored() -> None:
    runs = [
        _run("abc", [_gate("pytest", True, skipped=True)]),
        _run("abc", [_gate("pytest", False, skipped=True)]),
    ]

    assert passive_flaky(runs) == ()


def test_runs_without_sha_are_ignored() -> None:
    runs = [
        _run(None, [_gate("pytest", True)]),
        _run(None, [_gate("pytest", False)]),
    ]

    assert passive_flaky(runs) == ()


def test_stable_gate_is_not_flagged() -> None:
    runs = [
        _run("abc", [_gate("ruff", True)]),
        _run("abc", [_gate("ruff", True)]),
    ]

    assert passive_flaky(runs) == ()


def test_dirty_tree_runs_are_excluded() -> None:
    runs = [
        _run("abc", [_gate("pytest", True)], dirty=True),
        _run("abc", [_gate("pytest", False)], dirty=True),
    ]

    assert passive_flaky(runs) == ()


def test_runs_missing_dirty_flag_are_excluded() -> None:
    runs = [
        {"git_sha": "abc", "gates": [_gate("pytest", True)]},
        {"git_sha": "abc", "gates": [_gate("pytest", False)]},
    ]

    assert passive_flaky(runs) == ()


def test_render_passive_empty() -> None:
    assert render_passive(()) == ["no flaky gates in recent history"]


def test_render_passive_lists_each() -> None:
    lines = render_passive((FlakyGate("pytest", "abc1234", 3, 1),))

    assert "1 gates flipped" in lines[0]
    assert any("pytest @ abc1234" in line for line in lines)


def test_aggregate_flags_intermittent_tests() -> None:
    runs = [["t::a"], [], ["t::a"]]

    flaky = aggregate_reruns(runs)

    assert len(flaky) == 1
    assert flaky[0].test_id == "t::a"
    assert flaky[0].failures == 2
    assert flaky[0].runs == 3


def test_aggregate_ignores_consistently_failing() -> None:
    assert aggregate_reruns([["t::a"], ["t::a"], ["t::a"]]) == ()


def test_aggregate_ignores_never_failing() -> None:
    assert aggregate_reruns([[], [], []]) == ()


def test_aggregate_dedupes_within_a_run() -> None:
    flaky = aggregate_reruns([["t::a", "t::a"], []])

    assert flaky[0].failures == 1


def test_flaky_test_ratio() -> None:
    assert FlakyTest("t", 1, 4).ratio == 0.25
    assert FlakyTest("t", 0, 0).ratio == 0.0


def test_render_reruns_empty() -> None:
    assert render_reruns((), 5) == ["no flaky tests across 5 runs"]


def test_render_reruns_lists_each() -> None:
    lines = render_reruns((FlakyTest("t::a", 2, 3),), 3)

    assert "1 tests failed intermittently across 3 runs" in lines[0]
    assert any("t::a" in line and "2/3" in line for line in lines)


def test_run_reruns_aggregates_failures(tmp_path: Path, monkeypatch: Any) -> None:
    outputs = iter(
        [
            "FAILED tests/test_x.py::test_a - boom\n1 failed",
            "2 passed",
            "FAILED tests/test_x.py::test_a - boom\n1 failed",
        ]
    )

    def fake(name: str, command: list[str], cwd: Path) -> CompletedCommand:
        return CompletedCommand(name, tuple(command), cwd, 1, next(outputs), "")

    monkeypatch.setattr("kragg.flaky.run_command", fake)
    env = ProjectEnvironment(
        root=tmp_path,
        python=tmp_path / ".venv" / "bin" / "python",
        source=".venv",
    )

    flaky = run_reruns(tmp_path, env, KraggPolicy(), 3)

    assert len(flaky) == 1
    assert flaky[0].test_id == "tests/test_x.py::test_a"
    assert flaky[0].failures == 2
