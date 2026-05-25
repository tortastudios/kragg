from pathlib import Path
from typing import Any

from crag.cli import main


def test_policy_show_returns_success(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["policy", "show"]) == 0


def test_doctor_fails_without_project_files(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["doctor"]) == 1
