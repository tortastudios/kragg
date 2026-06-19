import json
from pathlib import Path

from kragg.coverage import critical_gaps, read_report, render_gaps


def _setup(
    tmp_path: Path,
    criticality: list[dict[str, object]],
    files: dict[str, object],
) -> None:
    pkg = tmp_path / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text("def vital() -> int:\n    return 1\n")
    (pkg / "io.py").write_text("def loader() -> int:\n    return 2\n")
    kragg_dir = tmp_path / ".kragg"
    kragg_dir.mkdir()
    (kragg_dir / "criticality.json").write_text(json.dumps(criticality))
    (kragg_dir / "coverage.json").write_text(json.dumps({"files": files}))


def test_gaps_ranked_by_fan_in_with_missing_lines(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        criticality=[
            {"name": "app.core.vital", "is_critical": True, "fan_in": 3},
            {"name": "app.io.loader", "is_critical": True, "fan_in": 7},
        ],
        files={
            "src/app/core.py": {"functions": {"vital": {"missing_lines": [2, 5]}}},
            "src/app/io.py": {"functions": {"loader": {"missing_lines": []}}},
        },
    )

    gaps = critical_gaps(tmp_path, ("src",))

    assert [g.qualname for g in gaps] == ["app.io.loader", "app.core.vital"]
    assert gaps[0].missing_lines == ()
    assert gaps[1].missing_lines == (2, 5)
    assert gaps[1].measured is True


def test_function_absent_from_report_is_unmeasured(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        criticality=[{"name": "app.core.vital", "is_critical": True, "fan_in": 4}],
        files={"src/app/core.py": {"functions": {}}},
    )

    gaps = critical_gaps(tmp_path, ("src",))

    assert gaps[0].measured is False
    assert gaps[0].missing_lines == ()


def test_absolute_coverage_keys_are_normalized(tmp_path: Path) -> None:
    abs_key = str(tmp_path / "src" / "app" / "core.py")
    _setup(
        tmp_path,
        criticality=[{"name": "app.core.vital", "is_critical": True, "fan_in": 4}],
        files={abs_key: {"functions": {"vital": {"missing_lines": [2]}}}},
    )

    gaps = critical_gaps(tmp_path, ("src",))

    assert gaps[0].measured is True
    assert gaps[0].missing_lines == (2,)


def test_read_report_missing_returns_none(tmp_path: Path) -> None:
    assert read_report(tmp_path) is None


def test_render_gaps_summarizes_and_lists(tmp_path: Path) -> None:
    _setup(
        tmp_path,
        criticality=[
            {"name": "app.core.vital", "is_critical": True, "fan_in": 3},
            {"name": "app.io.loader", "is_critical": True, "fan_in": 7},
        ],
        files={
            "src/app/core.py": {"functions": {"vital": {"missing_lines": [2, 5]}}},
            "src/app/io.py": {"functions": {"loader": {"missing_lines": []}}},
        },
    )

    lines = render_gaps(critical_gaps(tmp_path, ("src",)))

    assert "2 functions, 1 with gaps, 1 clean, 0 unmeasured" in lines[0]
    assert any("app.core.vital" in line and "2, 5" in line for line in lines)


def test_render_gaps_caps_long_line_lists(tmp_path: Path) -> None:
    many = list(range(1, 20))
    _setup(
        tmp_path,
        criticality=[{"name": "app.core.vital", "is_critical": True, "fan_in": 4}],
        files={"src/app/core.py": {"functions": {"vital": {"missing_lines": many}}}},
    )

    lines = render_gaps(critical_gaps(tmp_path, ("src",)))

    assert any("more" in line for line in lines)


def test_render_gaps_empty_when_no_critical(tmp_path: Path) -> None:
    _setup(tmp_path, criticality=[], files={})

    assert "no critical functions" in render_gaps(critical_gaps(tmp_path, ("src",)))[0]
