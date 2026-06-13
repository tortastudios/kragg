from kragg.check import FAST, SLOW, GateSpec, run_gates
from kragg.models import GateResult


def _spec(
    name: str,
    tier: str = FAST,
    passed: bool = True,
    skip_reason: str | None = None,
) -> GateSpec:
    return GateSpec(
        name=name,
        tier=tier,
        runner=lambda: GateResult(name=name, passed=passed),
        skip_reason=skip_reason,
    )


def test_all_fast_gates_run_despite_failure() -> None:
    results = run_gates([_spec("a", passed=False), _spec("b"), _spec("c")])

    assert [r.name for r in results] == ["a", "b", "c"]
    assert not any(r.skipped for r in results)


def test_slow_gates_skip_when_fast_gates_fail() -> None:
    results = run_gates([_spec("fast", passed=False), _spec("slow", tier=SLOW)])

    slow = results[1]
    assert slow.skipped
    assert slow.skip_reason == "static gates failed"


def test_force_slow_runs_slow_gates_anyway() -> None:
    results = run_gates(
        [_spec("fast", passed=False), _spec("slow", tier=SLOW)],
        force_slow=True,
    )

    assert not results[1].skipped


def test_fail_fast_halts_after_first_failure() -> None:
    results = run_gates(
        [_spec("a", passed=False), _spec("b"), _spec("c")],
        fail_fast=True,
    )

    assert not results[0].skipped
    assert results[1].skip_reason == "fail-fast"
    assert results[2].skip_reason == "fail-fast"


def test_preset_skip_reason_is_honored() -> None:
    results = run_gates([_spec("slow", tier=SLOW, skip_reason="incremental mode")])

    assert results[0].skipped
    assert results[0].skip_reason == "incremental mode"
