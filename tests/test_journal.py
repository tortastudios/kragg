import json
from pathlib import Path
from typing import Any

from kragg.journal import append_run, journal_path, read_runs
from kragg.models import GateResult
from kragg.report import ReportPayload, build_report, to_payload


def _payload(passed: bool = True) -> ReportPayload:
    report = build_report(
        command="check",
        mode="full",
        targets=("src",),
        results=[GateResult(name="ruff", passed=passed, duration_ms=10)],
        max_violations=25,
        started_at="2026-06-11T00:00:00+00:00",
        git_sha="abc1234",
    )
    return to_payload(report)


def test_append_and_read_runs(tmp_path: Path) -> None:
    append_run(tmp_path, _payload(passed=True))
    append_run(tmp_path, _payload(passed=False))

    runs = read_runs(tmp_path, 10)

    assert len(runs) == 2
    assert runs[0]["passed"] is True
    assert runs[1]["passed"] is False
    assert runs[1]["gates"][0]["name"] == "ruff"


def test_read_runs_skips_malformed_lines(tmp_path: Path) -> None:
    path = journal_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('not json\n{"passed": true}\n')

    runs = read_runs(tmp_path, 10)

    assert runs == [{"passed": True}]


def test_rotation_keeps_recent_lines(tmp_path: Path) -> None:
    path = journal_path(tmp_path)
    path.parent.mkdir(parents=True)
    filler: Any = {"passed": True}
    path.write_text("".join(json.dumps(filler) + "\n" for _ in range(1000)))

    append_run(tmp_path, _payload())

    lines = path.read_text().splitlines()
    assert len(lines) == 500
    assert json.loads(lines[-1])["command"] == "check"


def test_append_never_raises_when_unwritable(tmp_path: Path) -> None:
    (tmp_path / ".kragg").write_text("a file, not a directory")

    append_run(tmp_path, _payload())

    assert read_runs(tmp_path, 10) == []
