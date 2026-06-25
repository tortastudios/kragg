from pathlib import Path

from kragg.gates.typing_strictness import check_typing_strictness

STRICT = "[tool.mypy]\nstrict = true\n"


def _project(
    root: Path,
    pyproject: str,
    sources: dict[str, str] | None = None,
) -> None:
    (root / "pyproject.toml").write_text(pyproject)
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    for name, content in (sources or {}).items():
        (src / name).write_text(content)


def _codes(root: Path) -> set[str]:
    return {v.code for v in check_typing_strictness(root, ("src",)) if v.code}


def test_strict_config_passes(tmp_path: Path) -> None:
    _project(tmp_path, STRICT)

    assert check_typing_strictness(tmp_path, ("src",)) == ()


def test_missing_mypy_config_fails(tmp_path: Path) -> None:
    _project(tmp_path, '[project]\nname = "x"\n')

    assert "mypy-config-missing" in _codes(tmp_path)


def test_non_strict_config_fails(tmp_path: Path) -> None:
    _project(tmp_path, "[tool.mypy]\nwarn_return_any = true\n")

    assert "mypy-not-strict" in _codes(tmp_path)


def test_individual_core_flags_satisfy_floor(tmp_path: Path) -> None:
    _project(
        tmp_path,
        "[tool.mypy]\n"
        "disallow_untyped_defs = true\n"
        "check_untyped_defs = true\n"
        "warn_return_any = true\n"
        "disallow_any_generics = true\n",
    )

    assert check_typing_strictness(tmp_path, ("src",)) == ()


def test_ignore_errors_fails(tmp_path: Path) -> None:
    _project(tmp_path, "[tool.mypy]\nstrict = true\nignore_errors = true\n")

    assert "mypy-ignore-errors" in _codes(tmp_path)


def test_loosening_a_flag_fails(tmp_path: Path) -> None:
    _project(tmp_path, "[tool.mypy]\nstrict = true\ndisallow_untyped_defs = false\n")

    assert "mypy-loosened" in _codes(tmp_path)


def test_ignore_missing_imports_override_is_allowed(tmp_path: Path) -> None:
    _project(
        tmp_path,
        "[tool.mypy]\nstrict = true\n"
        '[[tool.mypy.overrides]]\nmodule = ["networkx.*"]\n'
        "ignore_missing_imports = true\n",
    )

    assert check_typing_strictness(tmp_path, ("src",)) == ()


def test_ignore_errors_override_fails(tmp_path: Path) -> None:
    _project(
        tmp_path,
        "[tool.mypy]\nstrict = true\n"
        '[[tool.mypy.overrides]]\nmodule = ["app.legacy"]\nignore_errors = true\n',
    )

    assert "mypy-ignore-errors" in _codes(tmp_path)


def test_bare_type_ignore_fails(tmp_path: Path) -> None:
    _project(tmp_path, STRICT, {"m.py": "x: int = None  # type: ignore\n"})

    assert "bare-type-ignore" in _codes(tmp_path)


def test_coded_type_ignore_passes(tmp_path: Path) -> None:
    _project(tmp_path, STRICT, {"m.py": "x: int = None  # type: ignore[assignment]\n"})

    assert check_typing_strictness(tmp_path, ("src",)) == ()


def test_revert_one_flag_goes_red_restore_goes_green(tmp_path: Path) -> None:
    """Proof it is the gate, not luck: strict is green; remove it and it is red."""
    _project(tmp_path, STRICT)
    assert check_typing_strictness(tmp_path, ("src",)) == ()

    (tmp_path / "pyproject.toml").write_text('[tool.mypy]\npython_version = "3.12"\n')
    assert check_typing_strictness(tmp_path, ("src",)) != ()
