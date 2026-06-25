"""Gate catalog: assembles the concrete check and security pipelines."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from kragg.check import FAST, SLOW, GateSpec, OutputParser
from kragg.coverage import COVERAGE_JSON_RELATIVE
from kragg.environment import (
    ProjectEnvironment,
    missing_interpreter_message,
    missing_module,
    remediation,
)
from kragg.gates import (
    architecture,
    critical_coverage,
    critical_tests,
    halstead,
    nullable_default,
    secrets,
    test_quality,
    type_complexity,
    typing_strictness,
)
from kragg.models import GateResult, Violation
from kragg.parsers import (
    parse_bandit_json,
    parse_mypy_output,
    parse_pip_audit_json,
    parse_pytest_output,
    parse_radon_cc,
    parse_radon_mi,
    parse_ruff_json,
)
from kragg.policy import KraggPolicy
from kragg.runner import run_command


def build_check_gates(
    root: Path,
    policy: KraggPolicy,
    env: ProjectEnvironment,
    targets: tuple[str, ...],
    incremental: bool = False,
) -> list[GateSpec]:
    """Assemble the full `kragg check` pipeline."""
    slow_skip = "incremental mode" if incremental else None
    (root / ".kragg").mkdir(parents=True, exist_ok=True)
    pytest_args = (
        "--cov=src",
        "--cov-report=term-missing",
        f"--cov-report=json:{COVERAGE_JSON_RELATIVE}",
        f"--cov-fail-under={policy.coverage_fail_under}",
        "-q",
    )
    return [
        GateSpec("ruff", FAST, lambda: _ruff_gate(root, targets)),
        GateSpec(
            "mypy",
            FAST,
            lambda: _project_tool_gate(
                "mypy", env, root, "mypy", targets, parse_mypy_output
            ),
        ),
        GateSpec(
            "typing-strictness",
            FAST,
            lambda: _typing_strictness_gate(root, policy),
        ),
        GateSpec("radon-cc", FAST, lambda: _radon_cc_gate(root, targets)),
        GateSpec("radon-mi", FAST, lambda: _radon_mi_gate(root, targets)),
        GateSpec("halstead", FAST, lambda: _halstead_gate(root, targets)),
        GateSpec(
            "type-complexity",
            FAST,
            lambda: _type_complexity_gate(root, policy, targets),
        ),
        GateSpec(
            "boundaries",
            FAST,
            lambda: _boundaries_gate(root, policy),
            skip_reason=None if len(policy.layers) >= 2 else "no layers configured",
        ),
        GateSpec("structure", FAST, lambda: _structure_gate(root, policy)),
        GateSpec(
            "nullable-default",
            FAST,
            lambda: _nullable_default_gate(root, policy),
        ),
        GateSpec(
            "critical-tests",
            FAST,
            lambda: _critical_tests_gate(root, policy),
            skip_reason=_no_criticality_reason(root),
        ),
        GateSpec("test-quality", FAST, lambda: _test_quality_gate(root, policy)),
        GateSpec("bandit", FAST, lambda: _bandit_gate(root, targets)),
        GateSpec("detect-secrets", FAST, lambda: _secrets_gate(root, targets)),
        GateSpec(
            "pytest-coverage",
            SLOW,
            lambda: _project_tool_gate(
                "pytest-coverage",
                env,
                root,
                "pytest",
                pytest_args,
                parse_pytest_output,
            ),
            skip_reason=slow_skip,
        ),
        GateSpec(
            "critical-coverage",
            SLOW,
            lambda: _critical_coverage_gate(root, policy),
            skip_reason=slow_skip or _no_criticality_reason(root),
        ),
        GateSpec(
            "pip-audit",
            SLOW,
            lambda: _project_tool_gate(
                "pip-audit",
                env,
                root,
                "pip_audit",
                ("-f", "json"),
                parse_pip_audit_json,
            ),
            skip_reason=slow_skip,
        ),
    ]


def _no_criticality_reason(root: Path) -> str | None:
    if (root / ".kragg" / "criticality.json").exists():
        return None
    return "no criticality data (run `kragg criticality --write`)"


def build_security_gates(
    root: Path,
    env: ProjectEnvironment,
    targets: tuple[str, ...],
    incremental: bool = False,
) -> list[GateSpec]:
    """Assemble the `kragg security` pipeline."""
    slow_skip = "incremental mode" if incremental else None
    return [
        GateSpec("bandit", FAST, lambda: _bandit_gate(root, targets)),
        GateSpec("detect-secrets", FAST, lambda: _secrets_gate(root, targets)),
        GateSpec(
            "pip-audit",
            SLOW,
            lambda: _project_tool_gate(
                "pip-audit",
                env,
                root,
                "pip_audit",
                ("-f", "json"),
                parse_pip_audit_json,
            ),
            skip_reason=slow_skip,
        ),
    ]


def _project_tool_gate(
    name: str,
    env: ProjectEnvironment,
    root: Path,
    module: str,
    args: tuple[str, ...],
    parser: OutputParser | None,
) -> GateResult:
    """Run an environment-dependent tool on the project interpreter."""
    if not env.found:
        return GateResult(
            name=name,
            passed=False,
            error=True,
            output=missing_interpreter_message(root),
        )
    command = env.module_command(module, *args)
    result = run_command(name, command, root)
    if not result.passed:
        missing = missing_module(result)
        if missing is not None and _is_tool_module(module, missing):
            return GateResult(
                name=name,
                passed=False,
                error=True,
                command=tuple(command),
                output=(
                    f"{module} is not installed in the project environment "
                    f"({env.describe()}).\n{remediation(missing)}"
                ),
            )
    violations = parser(result.stdout) if parser is not None else ()
    return GateResult(
        name=name,
        passed=result.passed,
        output="" if result.passed or violations else result.output,
        command=tuple(command),
        violations=violations,
        violation_count=len(violations),
    )


def _is_tool_module(module: str, missing: str) -> bool:
    """Only the tool itself missing is an environment error.

    A user-code import failing inside pytest also prints "No module named X";
    that is a test failure, not a broken environment.
    """
    return missing == module or (module == "pytest" and missing == "pytest_cov")


def _command_gate(
    name: str,
    command: list[str],
    root: Path,
    parser: OutputParser,
    error_codes: tuple[int, ...] = (),
) -> GateResult:
    result = run_command(name, command, root)
    violations = parser(result.stdout)
    return GateResult(
        name=name,
        passed=result.passed,
        output="" if result.passed or violations else result.output,
        command=tuple(command),
        violations=violations,
        violation_count=len(violations),
        error=result.returncode in error_codes,
    )


def _ruff_gate(root: Path, targets: tuple[str, ...]) -> GateResult:
    command = _kragg_module("ruff", "check", "--output-format", "json", *targets)

    def parse(stdout: str) -> tuple[Violation, ...]:
        return tuple(_relative_to_root(v, root) for v in parse_ruff_json(stdout))

    return _command_gate("ruff", command, root, parse, error_codes=(2,))


def _relative_to_root(violation: Violation, root: Path) -> Violation:
    if violation.file is None:
        return violation
    path = Path(violation.file)
    if path.is_absolute() and path.resolve().is_relative_to(root.resolve()):
        return replace(violation, file=str(path.resolve().relative_to(root.resolve())))
    return violation


def _radon_cc_gate(root: Path, targets: tuple[str, ...]) -> GateResult:
    command = _kragg_module("radon", "cc", *targets, "-s", "-n", "C")
    result = run_command("radon-cc", command, root)
    violations = parse_radon_cc(result.stdout)
    passed = result.passed and not result.stdout.strip()
    return GateResult(
        name="radon-cc",
        passed=passed,
        output="" if passed or violations else result.output,
        command=tuple(command),
        violations=violations,
        violation_count=len(violations),
    )


def _radon_mi_gate(root: Path, targets: tuple[str, ...]) -> GateResult:
    command = _kragg_module("radon", "mi", *targets, "-s")
    result = run_command("radon-mi", command, root)
    violations = parse_radon_mi(result.stdout)
    passed = result.passed and not violations
    return GateResult(
        name="radon-mi",
        passed=passed,
        output="" if passed or violations else result.output,
        command=tuple(command),
        violations=violations,
        violation_count=len(violations),
    )


def _halstead_gate(root: Path, targets: tuple[str, ...]) -> GateResult:
    violations: list[Violation] = []
    for target in targets:
        for failure in halstead.check_path(_resolve(root, target)):
            location, _, function = failure.location.partition("::")
            violations.append(
                Violation(
                    message=(
                        f"{function or location}: {failure.metric} "
                        f"{failure.actual:.1f} exceeds max {failure.maximum:.1f}"
                    ),
                    file=location,
                    code="halstead",
                    fix_hint="reduce operators/operands; split the function",
                )
            )
    return GateResult(
        name="halstead",
        passed=not violations,
        violations=tuple(violations),
        violation_count=len(violations),
    )


def _type_complexity_gate(
    root: Path,
    policy: KraggPolicy,
    targets: tuple[str, ...],
) -> GateResult:
    violations: list[Violation] = []
    for target in targets:
        found = type_complexity.check_path(
            _resolve(root, target),
            policy.type_max_nesting_depth,
            policy.type_max_length,
        )
        for item in found:
            violations.append(
                Violation(
                    message=(
                        f"{item.context}: annotation `{item.annotation_text}` "
                        f"(depth={item.depth}, length={item.length})"
                    ),
                    file=str(item.file_path),
                    line=item.line or None,
                    code="type-complexity",
                    fix_hint=item.suggestion,
                )
            )
    return GateResult(
        name="type-complexity",
        passed=not violations,
        violations=tuple(violations),
        violation_count=len(violations),
    )


def _nullable_default_gate(root: Path, policy: KraggPolicy) -> GateResult:
    violations = nullable_default.check_nullable_defaults(root, policy.source_paths)
    return GateResult(
        name="nullable-default",
        passed=not violations,
        violations=violations,
        violation_count=len(violations),
    )


def _typing_strictness_gate(root: Path, policy: KraggPolicy) -> GateResult:
    violations = typing_strictness.check_typing_strictness(root, policy.source_paths)
    return GateResult(
        name="typing-strictness",
        passed=not violations,
        violations=violations,
        violation_count=len(violations),
    )


def _boundaries_gate(root: Path, policy: KraggPolicy) -> GateResult:
    violations = architecture.check_layers(root, policy.source_paths, policy.layers)
    return GateResult(
        name="boundaries",
        passed=not violations,
        violations=violations,
        violation_count=len(violations),
    )


def _structure_gate(root: Path, policy: KraggPolicy) -> GateResult:
    violations = architecture.check_structure(
        root,
        policy.source_paths,
        policy.max_file_lines,
        policy.max_public_symbols,
        policy.structure_exclude,
    )
    return GateResult(
        name="structure",
        passed=not violations,
        violations=violations,
        violation_count=len(violations),
    )


def _critical_tests_gate(root: Path, policy: KraggPolicy) -> GateResult:
    violations = critical_tests.check_critical_tests(
        root,
        policy.source_paths,
        policy.test_paths,
    )
    return GateResult(
        name="critical-tests",
        passed=not violations,
        violations=violations,
        violation_count=len(violations),
    )


def _test_quality_gate(root: Path, policy: KraggPolicy) -> GateResult:
    violations = test_quality.check_tests(root, policy.test_paths)
    return GateResult(
        name="test-quality",
        passed=not violations,
        violations=violations,
        violation_count=len(violations),
    )


def _critical_coverage_gate(root: Path, policy: KraggPolicy) -> GateResult:
    violations = critical_coverage.check_critical_coverage(root, policy.source_paths)
    return GateResult(
        name="critical-coverage",
        passed=not violations,
        violations=violations,
        violation_count=len(violations),
    )


def _bandit_gate(root: Path, targets: tuple[str, ...]) -> GateResult:
    args = ["-ll", "-r", *targets, "-f", "json"]
    if (root / "pyproject.toml").exists():
        args = ["-c", "pyproject.toml", *args]
    command = _kragg_module("bandit", *args)
    return _command_gate("bandit", command, root, parse_bandit_json, error_codes=(2,))


def _secrets_gate(root: Path, targets: tuple[str, ...]) -> GateResult:
    try:
        baseline = secrets.load_baseline(root)
        violations = _scan_secrets(root, targets, baseline)
    except RuntimeError as exc:
        return GateResult(
            name="detect-secrets",
            passed=False,
            error=True,
            output=str(exc),
        )
    return GateResult(
        name="detect-secrets",
        passed=not violations,
        violations=violations,
        violation_count=len(violations),
    )


def _scan_secrets(
    root: Path,
    targets: tuple[str, ...],
    baseline: dict[str, list[str]],
) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    for target in targets:
        scan = secrets.scan_target(root, _resolve(root, target))
        for filepath, findings in scan.items():
            known = set(baseline.get(filepath, []))
            for finding in findings:
                hashed = finding.get("hashed_secret")
                if not hashed or hashed in known:
                    continue
                raw_line = finding.get("line_number")
                violations.append(
                    Violation(
                        message=f"potential secret: {finding.get('type', 'unknown')}",
                        file=filepath,
                        line=raw_line if isinstance(raw_line, int) else None,
                        code="secret",
                        fix_hint=(
                            "remove the credential; if reviewed and safe, add it "
                            "to .secrets.baseline"
                        ),
                    )
                )
    return tuple(violations)


def _kragg_module(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def _resolve(root: Path, target: str) -> Path:
    path = Path(target)
    return path if path.is_absolute() else root / path
