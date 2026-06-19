import json

from kragg.parsers import (
    parse_bandit_json,
    parse_failed_test_ids,
    parse_mypy_output,
    parse_pip_audit_json,
    parse_pytest_output,
    parse_radon_cc,
    parse_radon_mi,
    parse_ruff_json,
)


def test_parse_ruff_json() -> None:
    stdout = json.dumps(
        [
            {
                "filename": "src/app/main.py",
                "location": {"row": 4, "column": 8},
                "code": "F401",
                "message": "`os` imported but unused",
                "fix": {"applicability": "safe"},
            }
        ]
    )

    violations = parse_ruff_json(stdout)

    assert len(violations) == 1
    violation = violations[0]
    assert violation.file == "src/app/main.py"
    assert violation.line == 4
    assert violation.code == "F401"
    assert violation.fix_hint == "auto-fixable: run `kragg fix`"
    assert parse_ruff_json("not json") == ()


def test_parse_mypy_output() -> None:
    stdout = "\n".join(
        [
            "src/app/main.py:10:5: error: Incompatible return value type  "
            "[return-value]",
            "src/app/main.py:12: error: Missing return statement",
            "src/app/main.py:10:5: note: See documentation",
            "Found 2 errors in 1 file (checked 3 source files)",
        ]
    )

    violations = parse_mypy_output(stdout)

    assert len(violations) == 2
    assert violations[0].line == 10
    assert violations[0].column == 5
    assert violations[0].code == "return-value"
    assert violations[1].column is None


def test_parse_radon_cc() -> None:
    stdout = "src/app/main.py\n    F 10:0 process_data - C (15)\n"

    violations = parse_radon_cc(stdout)

    assert len(violations) == 1
    assert violations[0].file == "src/app/main.py"
    assert violations[0].line == 10
    assert "process_data" in violations[0].message


def test_parse_radon_mi() -> None:
    stdout = "src/good.py - A (87.20)\nsrc/bad.py - B (18.25)\n"

    violations = parse_radon_mi(stdout)

    assert len(violations) == 1
    assert violations[0].file == "src/bad.py"
    assert "grade B" in violations[0].message


def test_parse_bandit_json() -> None:
    stdout = json.dumps(
        {
            "results": [
                {
                    "filename": "src/app/main.py",
                    "line_number": 22,
                    "issue_text": "Possible hardcoded password",
                    "test_id": "B105",
                    "issue_severity": "LOW",
                }
            ]
        }
    )

    violations = parse_bandit_json(stdout)

    assert len(violations) == 1
    assert violations[0].code == "B105"
    assert violations[0].line == 22


def test_parse_pip_audit_json() -> None:
    stdout = json.dumps(
        {
            "dependencies": [
                {"name": "requests", "version": "2.31.0", "vulns": []},
                {
                    "name": "pip",
                    "version": "26.1.1",
                    "vulns": [{"id": "PYSEC-2026-196", "fix_versions": ["26.1.2"]}],
                },
            ]
        }
    )

    violations = parse_pip_audit_json(stdout)

    assert len(violations) == 1
    assert violations[0].code == "PYSEC-2026-196"
    assert "pip 26.1.1 is vulnerable (fixed in: 26.1.2)" in violations[0].message
    assert "uv pip install -U pip" in str(violations[0].fix_hint)


def test_parse_pytest_output() -> None:
    stdout = "\n".join(
        [
            "....F",
            "FAILED tests/test_app.py::test_main - AssertionError",
            "1 failed, 4 passed in 0.12s",
        ]
    )

    violations = parse_pytest_output(stdout)

    assert len(violations) == 1
    assert violations[0].file == "tests/test_app.py"
    assert "uv run pytest tests/test_app.py::test_main" in str(violations[0].fix_hint)


def test_parse_failed_test_ids() -> None:
    stdout = "\n".join(
        [
            "FAILED tests/test_app.py::test_main - AssertionError",
            "ERROR tests/test_app.py::test_setup - fixture error",
            "1 failed, 1 error, 4 passed in 0.12s",
        ]
    )

    assert parse_failed_test_ids(stdout) == [
        "tests/test_app.py::test_main",
        "tests/test_app.py::test_setup",
    ]
