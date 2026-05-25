from pathlib import Path

from crag.scaffold import create_new_project, normalize_package_name


def test_normalize_package_name() -> None:
    assert normalize_package_name("My-App") == "my_app"
    assert normalize_package_name("123") == "app_123"


def test_create_new_project_writes_expected_files(tmp_path: Path) -> None:
    target = tmp_path / "demo-app"

    written = create_new_project(target, "demo-app")

    assert written
    assert (target / "pyproject.toml").exists()
    assert (target / "src" / "demo_app" / "main.py").exists()
    assert "uv run crag check" in (target / "Makefile").read_text()
