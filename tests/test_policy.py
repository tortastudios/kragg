from pathlib import Path

from kragg.policy import load_policy


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
