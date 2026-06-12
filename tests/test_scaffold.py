from pathlib import Path

from crag.scaffold import create_new_project, initialize_project, normalize_package_name


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


def test_scaffold_emits_canonical_agent_contract(tmp_path: Path) -> None:
    target = tmp_path / "demo"

    create_new_project(target, "demo")

    agents = (target / "AGENTS.md").read_text()
    assert "uv run crag check --changed" in agents
    assert "exit codes" in agents.lower()
    assert "AGENTS.md" in (target / "CLAUDE.md").read_text()
    assert (
        '"contextFileName": "AGENTS.md"'
        in (target / ".gemini" / "settings.json").read_text()
    )


def test_scaffold_hooks_use_incremental_check(tmp_path: Path) -> None:
    target = tmp_path / "demo"

    create_new_project(target, "demo")

    settings = (target / ".claude" / "settings.json").read_text()
    assert "uv run crag check --changed" in settings
    assert '"Stop"' in settings


def test_scaffold_project_env_is_self_sufficient(tmp_path: Path) -> None:
    target = tmp_path / "demo"

    create_new_project(target, "demo")

    pyproject = (target / "pyproject.toml").read_text()
    assert "pytest>=" in pyproject
    assert "pytest-cov>=" in pyproject
    assert "mypy>=" in pyproject
    assert ".crag/" in (target / ".gitignore").read_text()


def test_initialize_project_adds_explicit_dev_group(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "existing"\n')

    initialize_project(tmp_path)

    pyproject = (tmp_path / "pyproject.toml").read_text()
    assert "[tool.crag]" in pyproject
    assert "pytest>=" in pyproject
