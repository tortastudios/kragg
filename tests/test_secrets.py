from pathlib import Path

import pytest

from kragg.gates.secrets import SecretFinding, find_new_secrets, scan_violations


def test_find_new_secrets_ignores_baseline_hashes() -> None:
    finding: SecretFinding = {
        "hashed_secret": "abc",
        "line_number": 10,
        "type": "Secret Keyword",
    }

    assert find_new_secrets({"src/app.py": [finding]}, {"src/app.py": ["abc"]}) == []


def test_find_new_secrets_reports_unknown_hashes() -> None:
    finding: SecretFinding = {
        "hashed_secret": "abc",
        "line_number": 10,
        "type": "Secret Keyword",
    }

    assert find_new_secrets({"src/app.py": [finding]}, {}) == [
        "  src/app.py:10 - Secret Keyword"
    ]


def test_scan_violations_reports_unbaselined_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finding: SecretFinding = {"hashed_secret": "abc", "line_number": 3, "type": "Hex"}
    monkeypatch.setattr(
        "kragg.gates.secrets.scan_target",
        lambda root, target: {"src/app.py": [finding]},
    )

    violations = scan_violations(tmp_path, ("src",), {})

    assert len(violations) == 1
    assert violations[0].code == "secret"
    assert violations[0].line == 3


def test_scan_violations_skips_baselined_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    finding: SecretFinding = {"hashed_secret": "abc", "line_number": 3, "type": "Hex"}
    monkeypatch.setattr(
        "kragg.gates.secrets.scan_target",
        lambda root, target: {"src/app.py": [finding]},
    )

    assert scan_violations(tmp_path, ("src",), {"src/app.py": ["abc"]}) == ()
