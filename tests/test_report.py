import json

from kragg.models import GateResult, Violation
from kragg.report import (
    EXIT_ENVIRONMENT,
    EXIT_GATE_FAILURES,
    EXIT_OK,
    build_report,
    cap_output,
    dedupe_violations,
    render_json,
    render_text,
    to_payload,
)


def _build(results: list[GateResult], max_violations: int = 25):  # type: ignore[no-untyped-def]
    return build_report(
        command="check",
        mode="full",
        targets=("src",),
        results=results,
        max_violations=max_violations,
        started_at="2026-06-11T00:00:00+00:00",
        git_sha="abc1234",
    )


def test_summary_counts_distinguish_passed_failed_skipped() -> None:
    payload = to_payload(
        _build(
            [
                GateResult(name="ruff", passed=True),
                GateResult(name="mypy", passed=False, violation_count=1),
                GateResult(name="pytest", passed=False, skipped=True),
            ]
        )
    )

    summary = payload["summary"]
    assert summary["gates_total"] == 3
    assert summary["gates_passed"] == 1
    assert summary["gates_failed"] == 1
    assert summary["gates_skipped"] == 1


def test_exit_code_mapping() -> None:
    assert _build([GateResult(name="ruff", passed=True)]).exit_code == EXIT_OK
    assert (
        _build([GateResult(name="ruff", passed=False)]).exit_code == EXIT_GATE_FAILURES
    )
    assert (
        _build([GateResult(name="mypy", passed=False, error=True)]).exit_code
        == EXIT_ENVIRONMENT
    )


def test_skipped_gates_do_not_fail_the_report() -> None:
    report = _build(
        [
            GateResult(name="ruff", passed=True),
            GateResult(name="pytest-coverage", passed=False, skipped=True),
        ]
    )

    assert report.passed
    assert report.exit_code == EXIT_OK


def test_dedupe_collapses_identical_findings() -> None:
    violations = tuple(
        Violation(message="`os` imported but unused", code="F401", file=f, line=1)
        for f in ("src/a.py", "src/b.py", "src/c.py")
    )

    deduped = dedupe_violations(violations)

    assert len(deduped) == 1
    assert "+2 more at src/b.py:1, src/c.py:1" in deduped[0].message


def test_violations_capped_and_marked_truncated() -> None:
    violations = tuple(
        Violation(message=f"violation {i}", code=str(i)) for i in range(5)
    )
    result = GateResult(
        name="ruff",
        passed=False,
        violations=violations,
        violation_count=5,
    )

    report = _build([result], max_violations=2)

    gate = report.gates[0]
    assert len(gate.shown) == 2
    assert gate.truncated


def test_payload_schema_shape() -> None:
    result = GateResult(
        name="ruff",
        passed=False,
        violations=(Violation(message="bad", file="src/a.py", line=3),),
        violation_count=1,
    )

    payload = to_payload(_build([result]))

    assert payload["schema_version"] == 1
    assert payload["passed"] is False
    assert payload["summary"]["gates_failed"] == 1
    assert payload["gates"][0]["violations"][0]["file"] == "src/a.py"
    parsed = json.loads(render_json(_build([result])))
    assert parsed["git_sha"] == "abc1234"


def test_cap_output_keeps_tail() -> None:
    output = "\n".join(f"line {i}" for i in range(100))

    capped = cap_output(output)

    assert capped.startswith("... [truncated, 100 lines total]")
    assert capped.endswith("line 99")


def test_next_actions_suggest_kragg_fix_for_fixable() -> None:
    result = GateResult(
        name="ruff",
        passed=False,
        violations=(Violation(message="x", fix_hint="auto-fixable: run `kragg fix`"),),
        violation_count=1,
    )

    text = render_text(_build([result]))

    assert "run `kragg fix` to auto-fix 1 ruff violations" in text


def test_next_actions_surface_environment_fixes() -> None:
    result = GateResult(
        name="mypy",
        passed=False,
        error=True,
        output="mypy is not installed.\nFix: uv add --dev mypy",
    )

    text = render_text(_build([result]))

    assert "mypy: Fix: uv add --dev mypy" in text


def test_render_text_shows_location_code_count_and_hint() -> None:
    result = GateResult(
        name="ruff",
        passed=False,
        violations=(
            Violation(
                message="bad",
                file="src/a.py",
                line=3,
                code="X1",
                fix_hint="do this",
            ),
        ),
        violation_count=1,
    )

    text = render_text(_build([result]))

    assert "[FAIL] ruff" in text
    assert "— 1 violations" in text
    assert "src/a.py:3 X1 bad -> do this" in text


def test_render_text_reports_truncation_count() -> None:
    violations = tuple(Violation(message=f"m{i}", code=str(i)) for i in range(5))
    result = GateResult(
        name="ruff",
        passed=False,
        violations=violations,
        violation_count=5,
    )

    text = render_text(_build([result], max_violations=2))

    assert "... 3 more not shown" in text


def test_render_text_has_no_next_action_when_passed() -> None:
    text = render_text(_build([GateResult(name="ruff", passed=True)]))

    assert "next:" not in text


def test_next_actions_point_at_violations_when_failed() -> None:
    result = GateResult(
        name="mypy",
        passed=False,
        violations=(Violation(message="bad", file="a.py", line=1),),
        violation_count=1,
    )

    assert "fix the violations" in render_text(_build([result]))


def test_dedupe_single_violation_has_no_more_suffix() -> None:
    deduped = dedupe_violations((Violation(message="solo", code="S1"),))

    assert deduped[0].message == "solo"


def test_dedupe_two_violations_report_one_more() -> None:
    violations = tuple(
        Violation(message="dup", code="D1", file=name, line=1)
        for name in ("a.py", "b.py")
    )

    deduped = dedupe_violations(violations)

    assert "(+1 more" in deduped[0].message
