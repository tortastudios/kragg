import json
from pathlib import Path

from crag.gates.test_quality import check_tests


def _write_test(tmp_path: Path, name: str, content: str) -> None:
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    (tests / name).write_text(content)


def test_assertion_free_test_is_flagged(tmp_path: Path) -> None:
    _write_test(
        tmp_path,
        "test_weak.py",
        "def test_runs_without_checking() -> None:\n    x = 1 + 1\n    print(x)\n",
    )

    violations = check_tests(tmp_path, ("tests",))

    assert len(violations) == 1
    assert violations[0].code == "no-assert"
    assert "test_runs_without_checking" in violations[0].message


def test_plain_assert_passes(tmp_path: Path) -> None:
    _write_test(
        tmp_path,
        "test_ok.py",
        "def test_math() -> None:\n    assert 1 + 1 == 2\n",
    )

    assert check_tests(tmp_path, ("tests",)) == ()


def test_pytest_raises_counts_as_assertion(tmp_path: Path) -> None:
    _write_test(
        tmp_path,
        "test_raises.py",
        "import pytest\n\n\ndef test_boom() -> None:\n"
        "    with pytest.raises(ValueError):\n        int('x')\n",
    )

    assert check_tests(tmp_path, ("tests",)) == ()


def test_mock_assert_methods_count(tmp_path: Path) -> None:
    _write_test(
        tmp_path,
        "test_mock.py",
        "from unittest.mock import Mock\n\n\ndef test_called() -> None:\n"
        "    m = Mock()\n    m()\n    m.assert_called_once()\n",
    )

    assert check_tests(tmp_path, ("tests",)) == ()


def test_unreferenced_critical_function_is_flagged(tmp_path: Path) -> None:
    _write_test(
        tmp_path,
        "test_ok.py",
        "def test_math() -> None:\n    assert 1 + 1 == 2\n",
    )
    crag_dir = tmp_path / ".crag"
    crag_dir.mkdir()
    (crag_dir / "criticality.json").write_text(
        json.dumps(
            [
                {"name": "app.core.vital", "is_critical": True},
                {"name": "app.core._secret", "is_critical": True},
            ]
        )
    )

    violations = check_tests(tmp_path, ("tests",))

    assert len(violations) == 1
    assert violations[0].code == "critical-untested"
    assert "app.core.vital" in violations[0].message


def test_referenced_critical_function_passes(tmp_path: Path) -> None:
    _write_test(
        tmp_path,
        "test_vital.py",
        "def test_vital_behavior() -> None:\n    assert 'vital'\n",
    )
    crag_dir = tmp_path / ".crag"
    crag_dir.mkdir()
    (crag_dir / "criticality.json").write_text(
        json.dumps([{"name": "app.core.vital", "is_critical": True}])
    )

    assert check_tests(tmp_path, ("tests",)) == ()


def test_no_tests_directory_passes(tmp_path: Path) -> None:
    assert check_tests(tmp_path, ("tests",)) == ()
