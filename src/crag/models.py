from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    """One actionable finding produced by a gate."""

    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    code: str | None = None
    fix_hint: str | None = None

    def location(self) -> str:
        if self.file is None:
            return ""
        parts = [self.file]
        if self.line is not None:
            parts.append(str(self.line))
            if self.column is not None:
                parts.append(str(self.column))
        return ":".join(parts)


@dataclass(frozen=True)
class GateResult:
    """Result produced by one guardrail gate."""

    name: str
    passed: bool
    output: str = ""
    command: tuple[str, ...] = ()
    skipped: bool = False
    skip_reason: str | None = None
    duration_ms: int = 0
    violations: tuple[Violation, ...] = ()
    violation_count: int = 0
    error: bool = False


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
