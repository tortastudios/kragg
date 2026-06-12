from pathlib import Path

from crag.gates.architecture import check_layers, check_structure

LAYERS = ("app.entrypoints", "app.services", "app.domain")


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_layered_app(tmp_path: Path) -> None:
    _write(tmp_path, "src/app/__init__.py", "")
    _write(tmp_path, "src/app/entrypoints/__init__.py", "")
    _write(tmp_path, "src/app/services/__init__.py", "")
    _write(tmp_path, "src/app/domain/__init__.py", "")
    _write(
        tmp_path,
        "src/app/entrypoints/cli.py",
        "from app.services.greeting import greet\n",
    )
    _write(
        tmp_path,
        "src/app/services/greeting.py",
        "from app.domain.messages import TEMPLATE\n\n\ndef greet() -> str:\n"
        "    return TEMPLATE\n",
    )
    _write(tmp_path, "src/app/domain/messages.py", 'TEMPLATE = "hi"\n')


def test_clean_layering_passes(tmp_path: Path) -> None:
    _make_layered_app(tmp_path)

    assert check_layers(tmp_path, ("src",), LAYERS) == ()


def test_upward_import_is_a_breach(tmp_path: Path) -> None:
    _make_layered_app(tmp_path)
    _write(
        tmp_path,
        "src/app/domain/bad.py",
        "from app.entrypoints.cli import greet\n",
    )

    violations = check_layers(tmp_path, ("src",), LAYERS)

    assert len(violations) == 1
    assert violations[0].code == "layer-breach"
    assert "app.domain.bad" in violations[0].message
    assert "app.entrypoints" in violations[0].message


def test_modules_outside_layers_are_unrestricted(tmp_path: Path) -> None:
    _make_layered_app(tmp_path)
    _write(
        tmp_path,
        "src/app/conftest_helper.py",
        "from app.entrypoints.cli import greet\n",
    )

    assert check_layers(tmp_path, ("src",), LAYERS) == ()


def test_layers_disabled_with_fewer_than_two(tmp_path: Path) -> None:
    _make_layered_app(tmp_path)
    _write(tmp_path, "src/app/domain/bad.py", "from app.entrypoints import cli\n")

    assert check_layers(tmp_path, ("src",), ("app.domain",)) == ()


def test_file_line_budget(tmp_path: Path) -> None:
    _write(tmp_path, "src/app/big.py", "x = 1\n" * 50)

    violations = check_structure(tmp_path, ("src",), 40, 20)

    assert len(violations) == 1
    assert violations[0].code == "file-budget"
    assert "51 lines" in violations[0].message


def test_public_symbol_budget(tmp_path: Path) -> None:
    defs = "\n\n".join(f"def func_{i}() -> None:\n    pass" for i in range(5))
    privates = "\n\n".join(f"def _hidden_{i}() -> None:\n    pass" for i in range(5))
    _write(tmp_path, "src/app/wide.py", f"{defs}\n\n{privates}\n")

    violations = check_structure(tmp_path, ("src",), 500, 4)

    assert len(violations) == 1
    assert violations[0].code == "symbol-budget"
    assert "5 public symbols" in violations[0].message


def test_structure_within_budgets_passes(tmp_path: Path) -> None:
    _make_layered_app(tmp_path)

    assert check_structure(tmp_path, ("src",), 500, 20) == ()
