import json
import subprocess
from pathlib import Path

from crag.brief import build_brief
from crag.policy import CragPolicy


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
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_vital() -> None:\n    assert 1\n"
    )
    (tmp_path / "README.md").write_text("readme\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")


def test_brief_groups_changes_and_names_critical_functions(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    crag_dir = tmp_path / ".crag"
    crag_dir.mkdir()
    (crag_dir / "criticality.json").write_text(
        json.dumps([{"name": "app.core.vital", "is_critical": True, "fan_in": 6}])
    )
    (tmp_path / "src" / "app" / "core.py").write_text(
        "def vital() -> int:\n    return 2\n"
    )
    (tmp_path / "tests" / "test_core.py").write_text(
        "def test_vital() -> None:\n    assert 2\n"
    )
    (tmp_path / "README.md").write_text("updated\n")

    text = build_brief(tmp_path, CragPolicy(), since=None)

    assert text is not None
    assert "# Change brief" in text
    assert "3 files changed" in text
    assert "## Source\n- src/app/core.py" in text
    assert "## Tests\n- tests/test_core.py" in text
    assert "## Other\n- README.md" in text
    assert "`app.core.vital` (fan-in 6)" in text
    assert "## Last gate run" in text


def test_brief_with_clean_tree(tmp_path: Path) -> None:
    _make_repo(tmp_path)

    text = build_brief(tmp_path, CragPolicy(), since=None)

    assert text is not None
    assert "0 files changed" in text
    assert "none" in text


def test_brief_since_ref(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    _git(tmp_path, "branch", "base")
    (tmp_path / "src" / "app" / "extra.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "more")

    text = build_brief(tmp_path, CragPolicy(), since="base")

    assert text is not None
    assert "src/app/extra.py" in text
    assert "vs base" in text


def test_brief_outside_git_returns_none(tmp_path: Path) -> None:
    assert build_brief(tmp_path, CragPolicy(), since=None) is None
