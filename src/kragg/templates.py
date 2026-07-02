"""Generated source content for project kinds and module generation.

Every kind shares one layered layout — entrypoints/services/domain — so
there is exactly one place everything goes and the boundaries gate can
enforce the direction of dependencies from the first commit.
"""

from __future__ import annotations

KINDS: tuple[str, ...] = ("cli", "api", "worker", "mcp")
MCP_SDKS: tuple[str, ...] = ("fastmcp", "official")


def kind_files(
    kind: str,
    package: str,
    project_name: str,
    mcp_sdk: str = "fastmcp",
) -> dict[str, str]:
    """Return source and test files for a project kind."""
    files = {
        f"src/{package}/__init__.py": f'"""{project_name} package."""\n',
        f"src/{package}/entrypoints/__init__.py": '"""Entrypoints layer."""\n',
        f"src/{package}/services/__init__.py": '"""Services layer."""\n',
        f"src/{package}/domain/__init__.py": '"""Domain layer."""\n',
        f"src/{package}/services/greeting.py": _greeting_service(package),
        f"src/{package}/domain/messages.py": MESSAGES_DOMAIN,
        "tests/__init__.py": "",
        "tests/test_greeting.py": _greeting_test(package),
    }
    if kind == "api":
        files[f"src/{package}/entrypoints/api.py"] = _api_entrypoint(
            package, project_name
        )
        files["tests/test_api.py"] = _api_test(package)
    elif kind == "worker":
        files[f"src/{package}/entrypoints/worker.py"] = _worker_entrypoint(package)
        files["tests/test_worker.py"] = _worker_test(package)
    elif kind == "mcp":
        files[f"src/{package}/entrypoints/server.py"] = _mcp_entrypoint(
            package, project_name, mcp_sdk
        )
        files["tests/test_server.py"] = _mcp_test(package, mcp_sdk)
    else:
        files[f"src/{package}/entrypoints/cli.py"] = _cli_entrypoint(
            package, project_name
        )
        files["tests/test_cli_entrypoint.py"] = _cli_test(package)
    return files


def kind_dependencies(kind: str, mcp_sdk: str = "fastmcp") -> list[str]:
    if kind == "api":
        return ['"fastapi>=0.115"', '"uvicorn>=0.30"']
    if kind == "mcp":
        if mcp_sdk == "official":
            return ['"mcp>=1.10"']
        return ['"fastmcp>=3.0"']
    return []


def kind_dev_extras(kind: str) -> list[str]:
    if kind == "api":
        return ['"httpx>=0.27"']
    return []


def kind_scripts(kind: str, project_name: str, package: str) -> str:
    if kind == "cli":
        return (
            f'\n[project.scripts]\n{project_name} = "{package}.entrypoints.cli:main"\n'
        )
    if kind == "mcp":
        return (
            "\n[project.scripts]\n"
            f'{project_name} = "{package}.entrypoints.server:main"\n'
        )
    return ""


def module_files(package: str, module: str) -> dict[str, str]:
    """Return generated files for `kragg gen module <name>`."""
    record = _record_name(module)
    return {
        f"src/{package}/domain/{module}.py": _module_domain(module, record),
        f"src/{package}/services/{module}.py": _module_service(package, module, record),
        f"tests/test_{module}.py": _module_test(package, module),
    }


def _record_name(module: str) -> str:
    return "".join(part.capitalize() for part in module.split("_")) + "Record"


MESSAGES_DOMAIN = '''"""Domain layer: pure data, no imports from above."""

GREETING_TEMPLATE = "Hello, {name}!"


def render_greeting(name: str) -> str:
    """Render the canonical greeting for a name."""
    return GREETING_TEMPLATE.format(name=name)
'''


def _greeting_service(package: str) -> str:
    return f'''"""Service: orchestrates domain logic for entrypoints."""

from {package}.domain.messages import render_greeting


def build_greeting(name: str) -> str:
    """Build the greeting shown to a user."""
    cleaned = name.strip() or "world"
    return render_greeting(cleaned)
'''


def _greeting_test(package: str) -> str:
    return f"""from {package}.services.greeting import build_greeting


def test_build_greeting() -> None:
    assert build_greeting("Ada") == "Hello, Ada!"


def test_blank_names_default_to_world() -> None:
    assert build_greeting("   ") == "Hello, world!"
"""


def _cli_entrypoint(package: str, project_name: str) -> str:
    return f'''"""Entrypoint: command-line interface."""

import argparse

from {package}.services.greeting import build_greeting


def main() -> None:
    """Parse arguments and greet."""
    parser = argparse.ArgumentParser(prog="{project_name}")
    parser.add_argument("name", nargs="?", default="world")
    args = parser.parse_args()
    print(build_greeting(args.name))


if __name__ == "__main__":
    main()
'''


def _cli_test(package: str) -> str:
    return f"""import pytest

from {package}.entrypoints.cli import main


def test_main_greets(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["prog", "Ada"])
    main()
    assert "Hello, Ada!" in capsys.readouterr().out
"""


def _api_entrypoint(package: str, project_name: str) -> str:
    return f'''"""Entrypoint: HTTP API."""

from fastapi import FastAPI

from {package}.services.greeting import build_greeting

app = FastAPI(title="{project_name}")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {{"status": "ok"}}


@app.get("/greet/{{name}}")
def greet(name: str) -> dict[str, str]:
    """Greet a user by name."""
    return {{"message": build_greeting(name)}}
'''


def _api_test(package: str) -> str:
    return f"""from fastapi.testclient import TestClient

from {package}.entrypoints.api import app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {{"status": "ok"}}


def test_greet() -> None:
    assert client.get("/greet/Ada").json() == {{"message": "Hello, Ada!"}}
"""


def _worker_entrypoint(package: str) -> str:
    return f'''"""Entrypoint: long-running worker."""

import time

from {package}.services.greeting import build_greeting


def tick() -> str:
    """Run one unit of work."""
    return build_greeting("worker")


def main(iterations: int = 0, interval_seconds: float = 1.0) -> None:
    """Run the worker loop; iterations=0 means run forever."""
    count = 0
    while iterations == 0 or count < iterations:
        print(tick())
        count += 1
        if iterations == 0 or count < iterations:
            time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
'''


def _worker_test(package: str) -> str:
    return f"""import pytest

from {package}.entrypoints.worker import main, tick


def test_tick() -> None:
    assert tick() == "Hello, worker!"


def test_main_runs_bounded_iterations(capsys: pytest.CaptureFixture[str]) -> None:
    main(iterations=2, interval_seconds=0)
    assert capsys.readouterr().out.count("Hello, worker!") == 2
"""


def _mcp_entrypoint(package: str, project_name: str, mcp_sdk: str) -> str:
    if mcp_sdk == "official":
        return _mcp_entrypoint_official(package, project_name)
    return f'''"""Entrypoint: MCP server."""

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from {package}.services.greeting import build_greeting

mcp = FastMCP("{project_name}")


@mcp.tool
def greet(name: str) -> str:
    """Greet a user by name."""
    return build_greeting(name)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Liveness probe for HTTP deployments."""
    return JSONResponse({{"status": "ok"}})


def main() -> None:
    """Run the MCP server over streamable HTTP."""
    mcp.run(transport="http")


if __name__ == "__main__":
    main()
'''


def _mcp_entrypoint_official(package: str, project_name: str) -> str:
    return f'''"""Entrypoint: MCP server."""

from mcp.server.fastmcp import FastMCP

from {package}.services.greeting import build_greeting

mcp = FastMCP("{project_name}")


@mcp.tool()
def greet(name: str) -> str:
    """Greet a user by name."""
    return build_greeting(name)


def main() -> None:
    """Run the MCP server over streamable HTTP."""
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
'''


def _mcp_test(package: str, mcp_sdk: str) -> str:
    if mcp_sdk == "official":
        return _mcp_test_official(package)
    return f'''import asyncio
import json

from fastmcp import Client
from starlette.requests import Request

from {package}.entrypoints.server import health, mcp


async def _call_greet(name: str) -> str:
    async with Client(mcp) as client:
        result = await client.call_tool("greet", {{"name": name}})
        return str(result.data)


def test_greet_tool() -> None:
    assert asyncio.run(_call_greet("Ada")) == "Hello, Ada!"


def test_health() -> None:
    request = Request({{"type": "http", "method": "GET", "headers": []}})
    response = asyncio.run(health(request))
    assert json.loads(bytes(response.body)) == {{"status": "ok"}}
'''


def _mcp_test_official(package: str) -> str:
    return f'''import asyncio

from mcp.types import TextContent

from {package}.entrypoints.server import mcp


async def _call_greet(name: str) -> str:
    content, _ = await mcp.call_tool("greet", {{"name": name}})
    block = content[0]
    assert isinstance(block, TextContent)
    return block.text


def test_greet_tool() -> None:
    assert asyncio.run(_call_greet("Ada")) == "Hello, Ada!"
'''


def _module_domain(module: str, record: str) -> str:
    return f'''"""Domain: {module} data and rules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class {record}:
    """One {module} entry."""

    id: str
    name: str
'''


def _module_service(package: str, module: str, record: str) -> str:
    return f'''"""Service: orchestrates {module} operations."""

from {package}.domain.{module} import {record}


def list_{module}(limit: int = 100) -> list[{record}]:
    """Return up to `limit` {module} records."""
    del limit
    return []
'''


def _module_test(package: str, module: str) -> str:
    return f"""from {package}.services.{module} import list_{module}


def test_list_{module}_starts_empty() -> None:
    assert list_{module}() == []
"""
