from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from crag.models import CompletedCommand


def run_command(name: str, command: Sequence[str], cwd: Path) -> CompletedCommand:
    """Run an external tool and capture its result."""
    result = subprocess.run(  # noqa: S603 - commands are framework-defined lists.
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return CompletedCommand(
        name=name,
        command=tuple(command),
        cwd=cwd,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
