from pathlib import Path

from kragg.spec import build_spec, render_spec


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
