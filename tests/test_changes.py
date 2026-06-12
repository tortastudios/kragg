import subprocess
from pathlib import Path

from crag.changes import changed_python_files


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed git commands in a test fixture.
        ["git", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
    )


def _make_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")


def test_returns_none_outside_git_repository(tmp_path: Path) -> None:
    assert changed_python_files(tmp_path, None, ("src",)) is None


def test_detects_modified_and_untracked_files(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    tracked = src / "a.py"
    tracked.write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")

    tracked.write_text("x = 2\n")
    (src / "b.py").write_text("y = 1\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "outside.py").write_text("z = 1\n")
    (src / "notes.txt").write_text("not python\n")

    files = changed_python_files(tmp_path, None, ("src", "tests"))

    assert files == ["src/a.py", "src/b.py"]


def test_no_changes_returns_empty_list(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")

    assert changed_python_files(tmp_path, None, ("src",)) == []


def test_since_uses_merge_base(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    _git(tmp_path, "branch", "base")

    (src / "a.py").write_text("x = 2\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "change")

    files = changed_python_files(tmp_path, "base", ("src",))

    assert files == ["src/a.py"]


def test_since_unknown_ref_returns_none(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")

    assert changed_python_files(tmp_path, "no-such-ref", ("src",)) is None
