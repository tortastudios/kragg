import json
from pathlib import Path

from crag.mapping import build_map, write_map
from crag.policy import CragPolicy

MODULE = '''
"""Demo module."""


def greet(name, punctuation):
    """Build a greeting for a user."""
    return f"hi {name}{punctuation}"


def _internal():
    pass


class Service:
    """Coordinates greetings."""

    def run(self, times):
        """Run the service loop."""
        return times

    def _setup(self):
        pass
'''


def _make_project(tmp_path: Path) -> None:
    package = tmp_path / "src" / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "core.py").write_text(MODULE)


def test_map_lists_public_symbols_with_docs(tmp_path: Path) -> None:
    _make_project(tmp_path)

    lines = build_map(tmp_path, CragPolicy())

    text = "\n".join(lines)
    assert "app.core" in text
    assert "greet(name, punctuation) — Build a greeting for a user." in text
    assert "class Service — Coordinates greetings." in text
    assert "Service.run(times) — Run the service loop." in text
    assert "_internal" not in text
    assert "_setup" not in text


def test_map_flags_critical_symbols(tmp_path: Path) -> None:
    _make_project(tmp_path)
    crag_dir = tmp_path / ".crag"
    crag_dir.mkdir()
    (crag_dir / "criticality.json").write_text(
        json.dumps([{"name": "app.core.greet", "is_critical": True, "risk": "HIGH"}])
    )

    text = "\n".join(build_map(tmp_path, CragPolicy()))

    assert "greet(name, punctuation) — Build a greeting for a user.  [HIGH]" in text


def test_write_map(tmp_path: Path) -> None:
    _make_project(tmp_path)
    output = tmp_path / ".crag" / "map.md"

    write_map(build_map(tmp_path, CragPolicy()), output)

    assert "app.core" in output.read_text()


def test_empty_project_yields_no_lines(tmp_path: Path) -> None:
    assert build_map(tmp_path, CragPolicy()) == []
