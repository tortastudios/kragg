import json
import subprocess
from pathlib import Path

from crag.gates.critical_tests import check_critical_tests


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed git commands in a test fixture.
        ["git", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
    )


def _make_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    package = tmp_path / "src" / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "core.py").write_text("def vital() -> int:\n    return 1\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_core.py").write_text("def test_vital() -> None:\n    assert 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    crag_dir = tmp_path / ".crag"
    crag_dir.mkdir()
    (crag_dir / "criticality.json").write_text(
        json.dumps(
            [
                {"name": "app.core.vital", "is_critical": True, "fan_in": 6},
                {"name": "app.core._hidden", "is_critical": True, "fan_in": 9},
            ]
        )
    )


def test_critical_change_without_tests_fails(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    (tmp_path / "src" / "app" / "core.py").write_text(
        "def vital() -> int:\n    return 2\n"
    )

    violations = check_critical_tests(tmp_path, ("src",), ("tests",))

    assert len(violations) == 1
    assert "app.core.vital" in violations[0].message
    assert "fan-in 6" in violations[0].message


def test_critical_change_with_test_change_passes(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    (tmp_path / "src" / "app" / "core.py").write_text(
        "def vital() -> int:\n    return 2\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_vital() -> None:\n    assert 2\n"
    )

    assert check_critical_tests(tmp_path, ("src",), ("tests",)) == ()


def test_non_critical_change_passes(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    (tmp_path / "src" / "app" / "other.py").write_text("x = 1\n")

    assert check_critical_tests(tmp_path, ("src",), ("tests",)) == ()


def test_private_critical_functions_are_exempt(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    (tmp_path / ".crag" / "criticality.json").write_text(
        json.dumps([{"name": "app.core._hidden", "is_critical": True, "fan_in": 9}])
    )
    (tmp_path / "src" / "app" / "core.py").write_text(
        "def vital() -> int:\n    return 3\n"
    )

    assert check_critical_tests(tmp_path, ("src",), ("tests",)) == ()


def test_no_git_repository_passes(tmp_path: Path) -> None:
    assert check_critical_tests(tmp_path, ("src",), ("tests",)) == ()


def test_clean_tree_passes(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    assert check_critical_tests(tmp_path, ("src",), ("tests",)) == ()
