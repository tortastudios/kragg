import dataclasses
import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kragg.policy import KraggPolicy, load_policy


def test_default_policy_values_are_pinned() -> None:
    policy = KraggPolicy()

    assert policy.profile == "strict-ai-python"
    assert policy.source_paths == ("src",)
    assert policy.test_paths == ("tests",)
    assert policy.coverage_fail_under == 80
    assert policy.type_max_nesting_depth == 2
    assert policy.type_max_length == 40
    assert policy.max_violations_per_gate == 25
    assert policy.max_file_lines == 500
    assert policy.max_public_symbols == 20
    assert policy.structure_exclude == ()
    assert policy.mutation_include == ()
    assert policy.mutation_exclude == ()
    assert policy.forbidden_calls == ()
    assert policy.secret_name_suffixes == (
        "_secret",
        "_token",
        "_password",
        "_passphrase",
        "_api_key",
        "_signing_key",
        "_secret_key",
        "_private_key",
        "_access_key",
    )


def test_policy_is_immutable() -> None:
    policy = KraggPolicy()

    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.coverage_fail_under = 1  # type: ignore[misc]


@given(threshold=st.integers(min_value=0, max_value=100))
def test_load_policy_round_trips_coverage_threshold(threshold: int) -> None:
    """For any valid threshold, a standalone kragg.toml reads back exactly."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "kragg.toml").write_text(f"coverage_fail_under = {threshold}\n")

        assert load_policy(root).coverage_fail_under == threshold


def test_load_policy_uses_pyproject_overrides(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.kragg]\n"
        'profile = "custom"\n'
        'source_paths = ["lib"]\n'
        "coverage_fail_under = 95\n"
    )

    policy = load_policy(tmp_path)

    assert policy.profile == "custom"
    assert policy.source_paths == ("lib",)
    assert policy.coverage_fail_under == 95
    assert policy.max_violations_per_gate == 25


def test_load_policy_reads_structure_exclude_list(tmp_path: Path) -> None:
    (tmp_path / "kragg.toml").write_text(
        'structure_exclude = ["src/app/icons.py", "*_pb2.py"]\n'
    )

    policy = load_policy(tmp_path)

    assert policy.structure_exclude == ("src/app/icons.py", "*_pb2.py")


def test_load_policy_reads_mutation_scope_lists(tmp_path: Path) -> None:
    (tmp_path / "kragg.toml").write_text(
        'mutation_include = ["src/billing/engine.py", "src/billing/*.py"]\n'
        'mutation_exclude = ["src/observability.py"]\n'
    )

    policy = load_policy(tmp_path)

    assert policy.mutation_include == ("src/billing/engine.py", "src/billing/*.py")
    assert policy.mutation_exclude == ("src/observability.py",)


def test_load_policy_reads_forbidden_calls_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.kragg]\n"
        'profile = "strict-ai-python"\n'
        "\n"
        "[tool.kragg.forbidden_calls]\n"
        '"subprocess.run" = "use app.runner.run_command"\n'
        '"starlette.requests.Request.body" = "use app.http.read_limited_body"\n'
    )

    policy = load_policy(tmp_path)

    assert policy.forbidden_calls == (
        ("starlette.requests.Request.body", "use app.http.read_limited_body"),
        ("subprocess.run", "use app.runner.run_command"),
    )


def test_forbidden_calls_with_non_string_hint_keeps_the_ban(tmp_path: Path) -> None:
    """A config typo in a hint must never silently disable the ban."""
    (tmp_path / "kragg.toml").write_text('[forbidden_calls]\n"subprocess.run" = 3\n')

    assert load_policy(tmp_path).forbidden_calls == (("subprocess.run", ""),)


def test_forbidden_calls_accepts_bare_list_of_paths(tmp_path: Path) -> None:
    (tmp_path / "kragg.toml").write_text(
        'forbidden_calls = ["subprocess.run", "pickle"]\n'
    )

    assert load_policy(tmp_path).forbidden_calls == (
        ("pickle", ""),
        ("subprocess.run", ""),
    )


def test_load_policy_reads_secret_name_suffixes(tmp_path: Path) -> None:
    (tmp_path / "kragg.toml").write_text(
        'secret_name_suffixes = ["_secret", "_kennwort"]\n'
    )

    assert load_policy(tmp_path).secret_name_suffixes == ("_secret", "_kennwort")


def test_kragg_toml_takes_precedence_over_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.kragg]\nprofile = "from-pyproject"\n'
    )
    (tmp_path / "kragg.toml").write_text(
        'profile = "from-kragg-toml"\nmax_violations_per_gate = 5\n'
    )

    policy = load_policy(tmp_path)

    assert policy.profile == "from-kragg-toml"
    assert policy.max_violations_per_gate == 5
