import json
import subprocess
import tomllib
from pathlib import Path

from kragg.mutation import build_config, format_test_command, select_targets
from kragg.policy import KraggPolicy

POLICY = KraggPolicy()


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed git commands in a test fixture.
        ["git", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, criticality: list[dict[str, object]]) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    pkg = tmp_path / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text("def vital() -> int:\n    return 1\n")
    (pkg / "util.py").write_text("def helper() -> int:\n    return 2\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    kragg_dir = tmp_path / ".kragg"
    kragg_dir.mkdir()
    (kragg_dir / "criticality.json").write_text(json.dumps(criticality))


def _two_criticals() -> list[dict[str, object]]:
    return [
        {"name": "app.core.vital", "is_critical": True, "fan_in": 5},
        {"name": "app.util.helper", "is_critical": True, "fan_in": 4},
    ]


def test_select_targets_changed_intersect_critical(tmp_path: Path) -> None:
    _repo(tmp_path, _two_criticals())
    (tmp_path / "src" / "app" / "core.py").write_text(
        "def vital() -> int:\n    return 9\n"
    )

    assert select_targets(tmp_path, POLICY, None, False) == ("src/app/core.py",)


def test_select_targets_clean_tree_is_empty(tmp_path: Path) -> None:
    _repo(tmp_path, _two_criticals())

    assert select_targets(tmp_path, POLICY, None, False) == ()


def test_select_targets_all_returns_all_critical_files(tmp_path: Path) -> None:
    _repo(tmp_path, _two_criticals())

    targets = select_targets(tmp_path, POLICY, None, True)

    assert set(targets) == {"src/app/core.py", "src/app/util.py"}


def test_select_targets_non_git_returns_none(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text("def vital() -> int:\n    return 1\n")
    kragg_dir = tmp_path / ".kragg"
    kragg_dir.mkdir()
    (kragg_dir / "criticality.json").write_text(
        json.dumps([{"name": "app.core.vital", "is_critical": True, "fan_in": 5}])
    )

    assert select_targets(tmp_path, POLICY, None, False) is None


def test_build_config_is_valid_toml() -> None:
    config = build_config("src/app/core.py", "py -m pytest -x -q tests", 25.0)

    data = tomllib.loads(config)

    assert data["cosmic-ray"]["module-path"] == "src/app/core.py"
    assert data["cosmic-ray"]["timeout"] == 25.0
    assert data["cosmic-ray"]["test-command"] == "py -m pytest -x -q tests"
    assert data["cosmic-ray"]["distributor"]["name"] == "local"


def test_format_test_command_joins_safely() -> None:
    command = format_test_command(("/venv/bin/python",), ("tests",))

    assert command == "/venv/bin/python -m pytest -x -q tests"
