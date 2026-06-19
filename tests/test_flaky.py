from typing import Any

from kragg.flaky import FlakyGate, passive_flaky, render_passive


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
