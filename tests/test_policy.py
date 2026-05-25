from pathlib import Path

from crag.policy import load_policy


def test_load_policy_uses_pyproject_overrides(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.crag]\n"
        'profile = "custom"\n'
        'source_paths = ["lib"]\n'
        "coverage_fail_under = 95\n"
    )

    policy = load_policy(tmp_path)

    assert policy.profile == "custom"
    assert policy.source_paths == ("lib",)
    assert policy.coverage_fail_under == 95
