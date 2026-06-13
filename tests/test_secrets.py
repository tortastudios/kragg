from kragg.gates.secrets import SecretFinding, find_new_secrets


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
