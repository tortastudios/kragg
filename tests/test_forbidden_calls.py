from pathlib import Path

from kragg.gates.forbidden_calls import check_forbidden_calls
from kragg.models import Violation

BODY_RULE = (
    ("starlette.requests.Request.body", "use app.http.read_limited_body"),
)


def _scan(
    tmp_path: Path,
    code: str,
    forbidden: tuple[tuple[str, str], ...],
) -> tuple[Violation, ...]:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "m.py").write_text(code)
    return check_forbidden_calls(tmp_path, ("src",), forbidden)


def test_flags_module_attribute_call(tmp_path: Path) -> None:
    code = "import subprocess\nsubprocess.run(['ls'])\n"
    rules = (("subprocess.run", "use app.runner.run_command"),)

    violations = _scan(tmp_path, code, rules)

    assert len(violations) == 1
    assert violations[0].code == "forbidden-call"
    assert violations[0].line == 2
    assert violations[0].fix_hint == "use app.runner.run_command"


def test_flags_aliased_from_import(tmp_path: Path) -> None:
    code = "from subprocess import run as sh\nsh(['ls'])\n"

    violations = _scan(tmp_path, code, (("subprocess.run", "wrap it"),))

    assert len(violations) == 1
    assert "subprocess.run" in violations[0].message


def test_flags_method_on_annotated_parameter(tmp_path: Path) -> None:
    code = (
        "from starlette.requests import Request\n"
        "async def handler(request: Request) -> bytes:\n"
        "    return await request.body()\n"
    )

    violations = _scan(tmp_path, code, BODY_RULE)

    assert len(violations) == 1
    assert violations[0].line == 3
    assert violations[0].fix_hint == "use app.http.read_limited_body"


def test_flags_method_on_nullable_annotated_parameter(tmp_path: Path) -> None:
    code = (
        "from starlette.requests import Request\n"
        "async def handler(request: Request | None) -> bytes:\n"
        "    assert request is not None\n"
        "    return await request.body()\n"
    )

    assert len(_scan(tmp_path, code, BODY_RULE)) == 1


def test_flags_method_on_constructed_instance(tmp_path: Path) -> None:
    code = "import httpx\nclient = httpx.Client()\nclient.get('http://x')\n"

    violations = _scan(tmp_path, code, (("httpx.Client.get", "use app.http"),))

    assert len(violations) == 1
    assert violations[0].line == 3


def test_prefix_entry_bans_everything_beneath_it(tmp_path: Path) -> None:
    code = "import pickle\npickle.loads(b'x')\n"

    violations = _scan(tmp_path, code, (("pickle", "use json"),))

    assert len(violations) == 1
    assert "banned: `pickle`" in violations[0].message


def test_call_result_is_not_treated_as_an_instance(tmp_path: Path) -> None:
    # `resp` holds requests.get's RESULT; only the get call itself may match.
    code = "import requests\nresp = requests.get('http://x')\nresp.json()\n"

    violations = _scan(tmp_path, code, (("requests.get", "wrap it"),))

    assert [violation.line for violation in violations] == [2]


def test_unresolvable_receiver_is_not_guessed(tmp_path: Path) -> None:
    code = "def f(thing):\n    return thing.body()\n"

    assert _scan(tmp_path, code, BODY_RULE) == ()


def test_self_method_is_out_of_scope_by_design(tmp_path: Path) -> None:
    code = (
        "class C:\n"
        "    def body(self) -> bytes: ...\n"
        "    def read(self) -> bytes:\n"
        "        return self.body()\n"
    )

    assert _scan(tmp_path, code, BODY_RULE) == ()


def test_decorator_call_resolves_in_enclosing_scope(tmp_path: Path) -> None:
    code = (
        "from flask import Flask\n"
        "app = Flask('x')\n"
        "@app.route('/x')\n"
        "def handler() -> str:\n"
        "    return 'ok'\n"
    )

    violations = _scan(tmp_path, code, (("flask.Flask.route", "use app.routes"),))

    assert len(violations) == 1


def test_inline_suppress_silences_the_wrapper_site(tmp_path: Path) -> None:
    code = "import subprocess\nsubprocess.run(['ls'])  # kragg: ignore - wrapper\n"

    assert _scan(tmp_path, code, (("subprocess.run", "wrap it"),)) == ()


def test_unrelated_calls_pass(tmp_path: Path) -> None:
    code = "import json\njson.loads('{}')\n"

    assert _scan(tmp_path, code, (("subprocess.run", "wrap it"),)) == ()


def test_empty_policy_scans_nothing(tmp_path: Path) -> None:
    assert check_forbidden_calls(tmp_path, ("src",), ()) == ()


def test_empty_hint_falls_back_to_generic_hint(tmp_path: Path) -> None:
    code = "import subprocess\nsubprocess.run(['ls'])\n"

    violations = _scan(tmp_path, code, (("subprocess.run", ""),))

    assert violations[0].fix_hint == "this API is forbidden by the project policy"


def test_most_specific_entry_wins(tmp_path: Path) -> None:
    code = "import subprocess\nsubprocess.run(['ls'])\n"
    rules = (("subprocess", "no subprocess at all"), ("subprocess.run", "use runner"))

    violations = _scan(tmp_path, code, rules)

    assert violations[0].fix_hint == "use runner"


def test_rebinding_clears_the_tracked_type(tmp_path: Path) -> None:
    # `client` inside fetch is the stub parameter, not the module-level Client
    code = (
        "import httpx\n"
        "client = httpx.Client()\n"
        "def fetch(stub):\n"
        "    client = stub\n"
        "    return client.get('http://x')\n"
    )

    assert _scan(tmp_path, code, (("httpx.Client.get", "wrap it"),)) == ()


def test_call_before_binding_is_not_flagged(tmp_path: Path) -> None:
    code = "import httpx\nclient.get('http://x')\nclient = httpx.Client()\n"

    assert _scan(tmp_path, code, (("httpx.Client.get", "wrap it"),)) == ()


def test_class_body_binding_does_not_leak_into_methods(tmp_path: Path) -> None:
    # Python class scope is invisible inside method bodies
    code = (
        "import httpx\n"
        "class C:\n"
        "    client = httpx.Client()\n"
        "    def fetch(self):\n"
        "        return client.get('http://x')\n"
    )

    assert _scan(tmp_path, code, (("httpx.Client.get", "wrap it"),)) == ()


def test_class_body_call_is_checked_in_class_scope(tmp_path: Path) -> None:
    code = (
        "import httpx\n"
        "class C:\n"
        "    client = httpx.Client()\n"
        "    data = client.get('http://x')\n"
    )

    violations = _scan(tmp_path, code, (("httpx.Client.get", "wrap it"),))

    assert [violation.line for violation in violations] == [4]


def test_parameter_default_expressions_are_scanned(tmp_path: Path) -> None:
    # defaults evaluate in the enclosing scope, at import time
    code = "import subprocess\ndef f(x=subprocess.run(['ls'])):\n    return x\n"

    violations = _scan(tmp_path, code, (("subprocess.run", "wrap it"),))

    assert [violation.line for violation in violations] == [2]


def test_comprehension_target_shadows_outer_binding(tmp_path: Path) -> None:
    code = (
        "import httpx\n"
        "client = httpx.Client()\n"
        "results = [client.get(u) for client in stubs]\n"
    )

    assert _scan(tmp_path, code, (("httpx.Client.get", "wrap it"),)) == ()


def test_for_target_clears_the_tracked_type(tmp_path: Path) -> None:
    code = (
        "import httpx\n"
        "client = httpx.Client()\n"
        "for client in stubs():\n"
        "    client.get('http://x')\n"
    )

    assert _scan(tmp_path, code, (("httpx.Client.get", "wrap it"),)) == ()
