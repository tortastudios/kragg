import json
from pathlib import Path

from kragg.spec import (
    build_spec,
    property_coverage,
    render_property_coverage,
    render_spec,
)


def _write_tests(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text(
        'def test_alpha_beta() -> None:\n'
        '    """Alpha verifies beta behavior."""\n'
        "    assert True\n\n\n"
        "def test_gamma() -> None:\n"
        "    assert True\n\n\n"
        "class TestThing:\n"
        "    def test_method_works(self) -> None:\n"
        "        assert True\n"
    )


def test_build_spec_humanizes_and_orders(tmp_path: Path) -> None:
    _write_tests(tmp_path)

    files = build_spec(tmp_path, ("tests",))

    assert len(files) == 1
    spec_file = files[0]
    assert spec_file.file == "tests/test_sample.py"
    assert [item.name for item in spec_file.items] == [
        "alpha beta",
        "gamma",
        "method works",
    ]
    assert spec_file.items[0].doc == "Alpha verifies beta behavior."
    assert spec_file.items[1].doc is None


def test_render_spec_outputs_tree(tmp_path: Path) -> None:
    _write_tests(tmp_path)

    lines = render_spec(build_spec(tmp_path, ("tests",)))

    assert "spec: 3 tests across 1 files" in lines[0]
    assert "tests/test_sample.py" in lines
    assert any("alpha beta: Alpha verifies beta behavior." in line for line in lines)


def test_build_spec_no_tests(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()

    assert build_spec(tmp_path, ("tests",)) == ()
    assert render_spec(()) == ["no tests found"]


def test_build_spec_skips_syntax_errors(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_broken.py").write_text("def test_x(:\n")

    assert build_spec(tmp_path, ("tests",)) == ()


def _setup_property(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text(
        "def vital() -> int:\n    return 1\n\n\ndef plain() -> int:\n    return 2\n"
    )
    kragg_dir = tmp_path / ".kragg"
    kragg_dir.mkdir()
    (kragg_dir / "criticality.json").write_text(
        json.dumps(
            [
                {"name": "app.core.vital", "is_critical": True, "fan_in": 7},
                {"name": "app.core.plain", "is_critical": True, "fan_in": 4},
            ]
        )
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_props.py").write_text(
        "from hypothesis import given, strategies as st\n"
        "from app.core import vital\n\n\n"
        "@given(st.integers())\n"
        "def test_vital_prop(n: int) -> None:\n"
        "    assert vital() == 1\n\n\n"
        "def test_plain_example() -> None:\n"
        "    assert True\n"
    )


def test_property_coverage_flags_only_example_based(tmp_path: Path) -> None:
    _setup_property(tmp_path)

    rows = property_coverage(tmp_path, ("src",), ("tests",))

    by_name = {row.qualname: row for row in rows}
    assert by_name["app.core.vital"].has_property_test is True
    assert by_name["app.core.plain"].has_property_test is False
    assert rows[0].qualname == "app.core.vital"


def test_render_property_coverage_lists_gaps(tmp_path: Path) -> None:
    _setup_property(tmp_path)

    lines = render_property_coverage(property_coverage(tmp_path, ("src",), ("tests",)))

    assert "1/2 critical functions" in lines[0]
    assert any("app.core.plain" in line and "example-based" in line for line in lines)


def test_render_property_coverage_empty_is_silent() -> None:
    assert render_property_coverage(()) == []
