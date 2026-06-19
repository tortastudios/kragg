import json
from pathlib import Path

from kragg.gates.critical_coverage import check_critical_coverage


def _setup(
    tmp_path: Path,
    criticality: list[dict[str, object]],
    files: dict[str, object] | None,
) -> None:
    pkg = tmp_path / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text("def vital() -> int:\n    return 1\n")
    kragg_dir = tmp_path / ".kragg"
    kragg_dir.mkdir()
    (kragg_dir / "criticality.json").write_text(json.dumps(criticality))
    if files is not None:
        (kragg_dir / "coverage.json").write_text(json.dumps({"files": files}))


def test_uncovered_critical_function_fails(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        [{"name": "app.core.vital", "is_critical": True, "fan_in": 5}],
        {"src/app/core.py": {"functions": {"vital": {"missing_lines": [2, 3]}}}},
    )

    violations = check_critical_coverage(tmp_path, ("src",))

    assert len(violations) == 1
    assert violations[0].code == "critical-coverage"
    assert violations[0].file == "src/app/core.py"
    assert violations[0].line == 2
    assert "app.core.vital" in violations[0].message


def test_fully_covered_critical_function_passes(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        [{"name": "app.core.vital", "is_critical": True, "fan_in": 5}],
        {"src/app/core.py": {"functions": {"vital": {"missing_lines": []}}}},
    )

    assert check_critical_coverage(tmp_path, ("src",)) == ()


def test_unmeasured_critical_function_does_not_fail(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        [{"name": "app.core.vital", "is_critical": True, "fan_in": 5}],
        {"src/app/core.py": {"functions": {}}},
    )

    assert check_critical_coverage(tmp_path, ("src",)) == ()


def test_missing_coverage_json_passes(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        [{"name": "app.core.vital", "is_critical": True, "fan_in": 5}],
        None,
    )

    assert check_critical_coverage(tmp_path, ("src",)) == ()
