import json
from pathlib import Path

import pytest

from kragg.gates.criticality import analyze, build_call_graph, format_report, write_json

CORE_PY = """
def helper() -> None:
    pass


def shared() -> None:
    helper()


class Service:
    def __init__(self) -> None:
        self.ready = True

    def run(self) -> None:
        self.step()

    def step(self) -> None:
        shared()
"""

API_PY = """
from pkg.core import Service, shared


def make_service() -> Service:
    return Service()


def handler(existing: Service) -> None:
    service = Service()
    service.run()
    existing.step()
    shared()
"""


def _make_package(tmp_path: Path) -> Path:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "core.py").write_text(CORE_PY)
    (package / "api.py").write_text(API_PY)
    return tmp_path


def test_build_call_graph_resolves_calls(tmp_path: Path) -> None:
    graph = build_call_graph(_make_package(tmp_path))

    edges = set(graph.edges)
    assert ("pkg.core.shared", "pkg.core.helper") in edges
    assert ("pkg.core.Service.run", "pkg.core.Service.step") in edges
    assert ("pkg.core.Service.step", "pkg.core.shared") in edges
    assert ("pkg.api.handler", "pkg.core.shared") in edges
    # constructor call resolves to __init__
    assert ("pkg.api.handler", "pkg.core.Service.__init__") in edges
    # receiver typed by constructor assignment
    assert ("pkg.api.handler", "pkg.core.Service.run") in edges
    # receiver typed by parameter annotation
    assert ("pkg.api.handler", "pkg.core.Service.step") in edges


def test_analyze_ranks_fan_in(tmp_path: Path) -> None:
    profiles = analyze(_make_package(tmp_path), fan_in_threshold=2)

    by_name = {profile.name: profile for profile in profiles}
    shared = by_name["pkg.core.shared"]
    assert shared.fan_in == 2
    assert shared.is_critical
    assert by_name["pkg.core.Service.step"].fan_in == 2


def test_missing_source_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        build_call_graph(tmp_path / "nope")


def test_format_report_sections(tmp_path: Path) -> None:
    report = format_report(analyze(_make_package(tmp_path), fan_in_threshold=2))

    assert "## Critical" in report
    assert "`pkg.core.shared`" in report


def test_write_json(tmp_path: Path) -> None:
    profiles = analyze(_make_package(tmp_path), fan_in_threshold=2)
    output = tmp_path / ".kragg" / "criticality.json"

    write_json(profiles, output)

    data = json.loads(output.read_text())
    names = [item["name"] for item in data]
    assert "pkg.core.shared" in names
    assert all({"fan_in", "risk", "is_critical"} <= set(item) for item in data)
