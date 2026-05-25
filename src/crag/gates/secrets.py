from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict, cast


class SecretFinding(TypedDict, total=False):
    """A single finding from detect-secrets."""

    hashed_secret: str
    line_number: int | str
    type: str


type ScanResults = dict[str, list[SecretFinding]]


def load_baseline(
    root: Path,
    baseline_name: str = ".secrets.baseline",
) -> dict[str, list[str]]:
    """Load reviewed secret hashes from a detect-secrets baseline."""
    baseline_path = root / baseline_name
    if not baseline_path.exists():
        return {}

    data = cast(dict[str, Any], json.loads(baseline_path.read_text()))
    raw_results = data.get("results", {})
    if not isinstance(raw_results, dict):
        return {}

    results: dict[str, list[str]] = {}
    for filepath, findings in raw_results.items():
        if not isinstance(filepath, str) or not isinstance(findings, list):
            continue
        hashes: list[str] = []
        for finding in findings:
            if isinstance(finding, dict) and isinstance(
                finding.get("hashed_secret"),
                str,
            ):
                hashes.append(finding["hashed_secret"])
        results[filepath] = hashes
    return results


def scan_target(root: Path, target: Path) -> ScanResults:
    """Run detect-secrets scan on a target path."""
    command = [sys.executable, "-m", "detect_secrets", "scan", str(target)]
    result = subprocess.run(  # noqa: S603 - command is framework-defined.
        command,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"detect-secrets scan failed: {result.stderr.strip()}")

    data = cast(dict[str, Any], json.loads(result.stdout))
    raw_results = data.get("results", {})
    if not isinstance(raw_results, dict):
        return {}
    return cast(ScanResults, raw_results)


def find_new_secrets(
    scan_results: ScanResults,
    baseline: dict[str, list[str]],
) -> list[str]:
    """Return descriptions for findings that are not in the baseline."""
    new_secrets: list[str] = []
    for filepath, findings in scan_results.items():
        baseline_hashes = set(baseline.get(filepath, []))
        for finding in findings:
            hashed_secret = finding.get("hashed_secret")
            if not hashed_secret or hashed_secret in baseline_hashes:
                continue
            line = finding.get("line_number", "?")
            secret_type = finding.get("type", "unknown")
            new_secrets.append(f"  {filepath}:{line} - {secret_type}")
    return new_secrets
