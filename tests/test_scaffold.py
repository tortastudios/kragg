from pathlib import Path

import pytest

from kragg.naming import normalize_package_name
from kragg.scaffold import (
    create_new_project,
    generate_module,
    initialize_project,
)


def test_normalize_package_name() -> None:
    assert normalize_package_name("My-App") == "my_app"
    assert normalize_package_name("123") == "app_123"


def test_create_new_project_writes_layered_layout(tmp_path: Path) -> None:
    target = tmp_path / "demo-app"

    written = create_new_project(target, "demo-app")

    assert written
    package = target / "src" / "demo_app"
    assert (package / "entrypoints" / "cli.py").exists()
    assert (package / "services" / "greeting.py").exists()
    assert (package / "domain" / "messages.py").exists()
    assert (target / "tests" / "test_greeting.py").exists()
    assert "uv run kragg check" in (target / "Makefile").read_text()
    pyproject = (target / "pyproject.toml").read_text()
    assert (
        'layers = ["demo_app.entrypoints", "demo_app.services", "demo_app.domain"]'
        in pyproject
    )
    assert 'demo-app = "demo_app.entrypoints.cli:main"' in pyproject


def test_api_kind_uses_fastapi(tmp_path: Path) -> None:
    target = tmp_path / "svc"

    create_new_project(target, "svc", kind="api")

    assert (target / "src" / "svc" / "entrypoints" / "api.py").exists()
    pyproject = (target / "pyproject.toml").read_text()
    assert "fastapi" in pyproject
    assert "httpx" in pyproject
    assert "[project.scripts]" not in pyproject


def test_worker_kind_has_bounded_loop(tmp_path: Path) -> None:
    target = tmp_path / "jobs"

    create_new_project(target, "jobs", kind="worker")

    worker = (target / "src" / "jobs" / "entrypoints" / "worker.py").read_text()
    assert "def tick()" in worker
    assert (target / "tests" / "test_worker.py").exists()


def test_unknown_kind_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_new_project(tmp_path / "x", "x", kind="spaceship")


def test_mcp_kind_defaults_to_fastmcp(tmp_path: Path) -> None:
    target = tmp_path / "brain-mcp"

    create_new_project(target, "brain-mcp", kind="mcp")

    server = (target / "src" / "brain_mcp" / "entrypoints" / "server.py").read_text()
    assert "from fastmcp import FastMCP" in server
    assert "@mcp.custom_route" in server
    test = (target / "tests" / "test_server.py").read_text()
    assert "from fastmcp import Client" in test
    pyproject = (target / "pyproject.toml").read_text()
    assert "fastmcp>=" in pyproject
    assert 'brain-mcp = "brain_mcp.entrypoints.server:main"' in pyproject


def test_mcp_kind_official_sdk(tmp_path: Path) -> None:
    target = tmp_path / "brain-mcp"

    create_new_project(target, "brain-mcp", kind="mcp", mcp_sdk="official")

    server = (target / "src" / "brain_mcp" / "entrypoints" / "server.py").read_text()
    assert "from mcp.server.fastmcp import FastMCP" in server
    pyproject = (target / "pyproject.toml").read_text()
    assert '"mcp>=' in pyproject
    assert "fastmcp" not in pyproject


def test_unknown_mcp_sdk_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_new_project(tmp_path / "x", "x", kind="mcp", mcp_sdk="homegrown")


def test_shadowing_names_are_refused_with_remediation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--package"):
        create_new_project(tmp_path / "mcp", "mcp", kind="mcp")
    with pytest.raises(ValueError, match="standard library"):
        create_new_project(tmp_path / "json", "json")
    assert not (tmp_path / "mcp").exists()


def test_package_override_escapes_shadowing(tmp_path: Path) -> None:
    target = tmp_path / "mcp"

    create_new_project(target, "mcp", kind="mcp", package_name="brain_mcp")

    assert (target / "src" / "brain_mcp" / "entrypoints" / "server.py").exists()
    pyproject = (target / "pyproject.toml").read_text()
    assert 'name = "mcp"' in pyproject
    assert 'packages = ["src/brain_mcp"]' in pyproject


def test_allow_shadowing_downgrades_refusal(tmp_path: Path) -> None:
    target = tmp_path / "mcp"

    written = create_new_project(target, "mcp", kind="mcp", allow_shadowing=True)

    assert written
    assert (target / "src" / "mcp" / "entrypoints" / "server.py").exists()


def test_scaffold_emits_canonical_agent_contract(tmp_path: Path) -> None:
    target = tmp_path / "demo"

    create_new_project(target, "demo")

    agents = (target / "AGENTS.md").read_text()
    assert "uv run kragg check --changed" in agents
    assert "exit codes" in agents.lower()
    assert "kragg gen module" in agents
    assert "AGENTS.md" in (target / "CLAUDE.md").read_text()
    assert (
        '"contextFileName": "AGENTS.md"'
        in (target / ".gemini" / "settings.json").read_text()
    )


def test_scaffold_hooks_use_adapter(tmp_path: Path) -> None:
    target = tmp_path / "demo"

    create_new_project(target, "demo")

    settings = (target / ".claude" / "settings.json").read_text()
    assert "uv run kragg hook claude" in settings
    assert '"Stop"' in settings
    assert '"SessionStart"' in settings


def test_scaffold_project_env_is_self_sufficient(tmp_path: Path) -> None:
    target = tmp_path / "demo"

    create_new_project(target, "demo")

    pyproject = (target / "pyproject.toml").read_text()
    assert "pytest>=" in pyproject
    assert "pytest-cov>=" in pyproject
    assert "mypy>=" in pyproject
    assert ".kragg/" in (target / ".gitignore").read_text()


def test_initialize_project_adds_guardrails_without_skeleton(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "existing"\n')

    initialize_project(tmp_path)

    pyproject = (tmp_path / "pyproject.toml").read_text()
    assert "[tool.kragg]" in pyproject
    assert "pytest>=" in pyproject
    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "src").exists()


def test_generate_module_creates_slots(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    create_new_project(target, "demo")

    written = generate_module(target, "payment-methods")

    names = [str(path.relative_to(target)) for path in written]
    assert "src/demo/domain/payment_methods.py" in names
    assert "src/demo/services/payment_methods.py" in names
    assert "tests/test_payment_methods.py" in names
    domain = (target / "src" / "demo" / "domain" / "payment_methods.py").read_text()
    assert "class PaymentMethodsRecord" in domain


def test_generate_module_refuses_duplicates(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    create_new_project(target, "demo")
    generate_module(target, "billing")

    with pytest.raises(FileExistsError):
        generate_module(target, "billing")


def test_generate_module_requires_single_package(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        generate_module(tmp_path, "billing")
