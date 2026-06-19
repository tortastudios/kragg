import json
from pathlib import Path

from kragg.critical import critical_files, critical_functions


def _make_tree(tmp_path: Path, entries: list[dict[str, object]]) -> None:
    package = tmp_path / "src" / "app"
    sub = package / "sub"
    sub.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "core.py").write_text(
        "def vital() -> int:\n    return 1\n\n\nclass Engine:\n"
        "    def run(self) -> int:\n        return 2\n"
    )
    (sub / "__init__.py").write_text("")
    (sub / "leaf.py").write_text("def helper() -> int:\n    return 3\n")
    kragg_dir = tmp_path / ".kragg"
    kragg_dir.mkdir()
    (kragg_dir / "criticality.json").write_text(json.dumps(entries))


def test_resolves_module_function_to_file_and_key(tmp_path: Path) -> None:
    _make_tree(tmp_path, [{"name": "app.core.vital", "is_critical": True, "fan_in": 6}])

    functions = critical_functions(tmp_path, ("src",))

    assert len(functions) == 1
    fn = functions[0]
    assert fn.qualname == "app.core.vital"
    assert fn.file == "src/app/core.py"
    assert fn.fn_key == "vital"
    assert fn.fan_in == 6


def test_resolves_method_to_class_dot_method_key(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        [{"name": "app.core.Engine.run", "is_critical": True, "fan_in": 4}],
    )

    fn = critical_functions(tmp_path, ("src",))[0]

    assert fn.file == "src/app/core.py"
    assert fn.fn_key == "Engine.run"


def test_resolves_nested_package_module(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        [{"name": "app.sub.leaf.helper", "is_critical": True, "fan_in": 3}],
    )

    fn = critical_functions(tmp_path, ("src",))[0]

    assert fn.file == "src/app/sub/leaf.py"
    assert fn.fn_key == "helper"


def test_skips_private_and_non_critical(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        [
            {"name": "app.core._hidden", "is_critical": True, "fan_in": 9},
            {"name": "app.core.vital", "is_critical": False, "fan_in": 1},
        ],
    )

    assert critical_functions(tmp_path, ("src",)) == ()


def test_missing_criticality_json_returns_empty(tmp_path: Path) -> None:
    assert critical_functions(tmp_path, ("src",)) == ()


def test_unresolvable_qualname_is_dropped(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        [{"name": "other.pkg.ghost", "is_critical": True, "fan_in": 5}],
    )

    assert critical_functions(tmp_path, ("src",)) == ()


def test_missing_fan_in_defaults_to_zero(tmp_path: Path) -> None:
    _make_tree(tmp_path, [{"name": "app.core.vital", "is_critical": True}])

    assert critical_functions(tmp_path, ("src",))[0].fan_in == 0


def test_critical_files_dedupes_by_file(tmp_path: Path) -> None:
    _make_tree(
        tmp_path,
        [
            {"name": "app.core.vital", "is_critical": True, "fan_in": 6},
            {"name": "app.core.Engine.run", "is_critical": True, "fan_in": 4},
            {"name": "app.sub.leaf.helper", "is_critical": True, "fan_in": 3},
        ],
    )

    files = critical_files(tmp_path, ("src",))

    assert files == ("src/app/core.py", "src/app/sub/leaf.py")
