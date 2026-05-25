from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateResult:
    """Result produced by one guardrail gate."""

    name: str
    passed: bool
    output: str = ""
    command: tuple[str, ...] = ()
    skipped: bool = False


@dataclass(frozen=True)
class CompletedCommand:
    """Captured result for an external command."""

    name: str
    command: tuple[str, ...]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part).strip()

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def to_gate_result(self) -> GateResult:
        return GateResult(
            name=self.name,
            passed=self.passed,
            output=self.output,
            command=self.command,
        )


@dataclass(frozen=True)
class ProjectContext:
    """Resolved project root and active policy."""

    root: Path
    policy_name: str
