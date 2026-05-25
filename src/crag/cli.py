from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from crag.gates import criticality, halstead, secrets, type_complexity
from crag.models import CompletedCommand
from crag.policy import load_policy
from crag.runner import run_command
from crag.scaffold import create_new_project, initialize_project


def main(argv: Sequence[str] | None = None) -> int:
    """Run the crag command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = cast(
        Callable[[argparse.Namespace], int] | None,
        getattr(args, "handler", None),
    )
    if handler is None:
        parser.print_help()
        return 2
    return handler(args)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="crag")
    subparsers = parser.add_subparsers(dest="command")

    new_parser = subparsers.add_parser("new", help="create a new project")
    new_parser.add_argument("name")
    new_parser.set_defaults(handler=cmd_new)

    init_parser = subparsers.add_parser("init", help="add crag to a project")
    init_parser.add_argument("path", nargs="?", default=".")
    init_parser.set_defaults(handler=cmd_init)

    check_parser = subparsers.add_parser("check", help="run quality gates")
    check_parser.add_argument("--file", dest="target")
    check_parser.set_defaults(handler=cmd_check)

    fix_parser = subparsers.add_parser("fix", help="format and safely fix lint")
    fix_parser.add_argument("--file", dest="target")
    fix_parser.set_defaults(handler=cmd_fix)

    security_parser = subparsers.add_parser("security", help="run security gates")
    security_parser.add_argument("--file", dest="target")
    security_parser.set_defaults(handler=cmd_security)

    audit_parser = subparsers.add_parser("audit", help="run architecture audit")
    audit_parser.set_defaults(handler=cmd_audit)

    criticality_parser = subparsers.add_parser(
        "criticality",
        help="analyze call-graph criticality",
    )
    criticality_parser.add_argument("--write", action="store_true")
    criticality_parser.add_argument("--path", default=None)
    criticality_parser.set_defaults(handler=cmd_criticality)

    doctor_parser = subparsers.add_parser("doctor", help="verify project setup")
    doctor_parser.set_defaults(handler=cmd_doctor)

    policy_parser = subparsers.add_parser("policy", help="inspect policies")
    policy_subparsers = policy_parser.add_subparsers(
        dest="policy_command",
        required=True,
    )
    policy_show = policy_subparsers.add_parser("show", help="show active policy")
    policy_show.set_defaults(handler=cmd_policy_show)

    return parser


def cmd_new(args: argparse.Namespace) -> int:
    target = Path(args.name).resolve()
    try:
        written = create_new_project(target, target.name)
    except FileExistsError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Created {target}")
    print(f"Wrote {len(written)} files")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    written = initialize_project(root)
    print(f"Initialized crag in {root}")
    print(f"Wrote {len(written)} files")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path.cwd()
    policy = load_policy(root)
    target = _target_or_default(args.target, policy.source_paths)

    if _run_external("ruff", _module("ruff", "check", target), root) != 0:
        return 1
    if _run_external("mypy", _module("mypy", target), root) != 0:
        return 1
    if _run_radon(root, target) != 0:
        return 1
    if _run_type_complexity(root, target) != 0:
        return 1
    if _run_coverage(root, target, policy.coverage_fail_under) != 0:
        return 1
    if _run_security(root, target) != 0:
        return 1

    print(f"All quality gates passed for {target}")
    return 0


def cmd_fix(args: argparse.Namespace) -> int:
    root = Path.cwd()
    policy = load_policy(root)
    target = _target_or_default(args.target, policy.source_paths)
    for command_name, command in (
        ("ruff format", _module("ruff", "format", target)),
        ("ruff fix", _module("ruff", "check", "--fix", target)),
    ):
        if _run_external(command_name, command, root) != 0:
            return 1
    return 0


def cmd_security(args: argparse.Namespace) -> int:
    root = Path.cwd()
    policy = load_policy(root)
    target = _target_or_default(args.target, policy.source_paths)
    return _run_security(root, target)


def cmd_audit(args: argparse.Namespace) -> int:
    del args
    root = Path.cwd()
    policy = load_policy(root)
    source = policy.source_paths[0]
    if cmd_criticality(argparse.Namespace(write=True, path=source)) != 0:
        return 1
    if _run_external("vulture", _module("vulture", source), root) != 0:
        return 1
    if _run_external("deptry", _module("deptry", source), root) != 0:
        return 1
    print("Audit complete")
    return 0


def cmd_criticality(args: argparse.Namespace) -> int:
    root = Path.cwd()
    policy = load_policy(root)
    source = Path(args.path or policy.source_paths[0])
    src_dir = source if source.is_absolute() else root / source
    try:
        profiles = criticality.analyze(src_dir)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.write:
        output = root / "CRITICALITY.md"
        criticality.write_report(profiles, output)
        print(f"Wrote {output}")
    else:
        criticality.print_table(profiles)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    del args
    root = Path.cwd()
    policy = load_policy(root)
    checks = [
        ("pyproject.toml", (root / "pyproject.toml").exists()),
        ("uv", shutil.which("uv") is not None),
        ("source path", any((root / path).exists() for path in policy.source_paths)),
        ("test path", any((root / path).exists() for path in policy.test_paths)),
    ]
    failed = False
    for label, passed in checks:
        status = "ok" if passed else "missing"
        print(f"{label}: {status}")
        failed = failed or not passed
    return 1 if failed else 0


def cmd_policy_show(args: argparse.Namespace) -> int:
    del args
    policy = load_policy(Path.cwd())
    print(json.dumps(policy.as_dict(), indent=2, sort_keys=True))
    return 0


def _run_radon(root: Path, target: str) -> int:
    cc = run_command("radon cc", _module("radon", "cc", target, "-s", "-n", "C"), root)
    _print_command(cc)
    if not cc.passed or cc.stdout.strip():
        print("Functions graded C or worse found (max allowed: B)")
        return 1

    mi = run_command("radon mi", _module("radon", "mi", target, "-s"), root)
    _print_command(mi)
    if not mi.passed:
        return 1
    bad_mi = [
        line for line in mi.stdout.splitlines() if line.rstrip().endswith((" B", " C"))
    ]
    if bad_mi:
        print("\n".join(bad_mi))
        print("Files with MI grade B or C found (minimum: A)")
        return 1

    failures = halstead.check_path(_resolve(root, target))
    if failures:
        print("Halstead violations:")
        for failure in failures:
            print(halstead.format_violation(failure))
        return 1
    print("halstead: ok")
    return 0


def _run_type_complexity(root: Path, target: str) -> int:
    policy = load_policy(root)
    violations = type_complexity.check_path(
        _resolve(root, target),
        policy.type_max_nesting_depth,
        policy.type_max_length,
    )
    if violations:
        print("Type annotation complexity violations:")
        for violation in violations:
            print(type_complexity.format_violation(violation))
        return 1
    print("type complexity: ok")
    return 0


def _run_coverage(root: Path, target: str, fail_under: int) -> int:
    target_path = _resolve(root, target)
    if target_path.is_file():
        print("pytest + coverage: skipped for single-file check")
        return 0
    command = _module(
        "pytest",
        "--cov=src",
        "--cov-report=term-missing",
        f"--cov-fail-under={fail_under}",
        "-q",
    )
    return _run_external("pytest + coverage", command, root)


def _run_security(root: Path, target: str) -> int:
    pyproject = root / "pyproject.toml"
    bandit_command = _module("bandit", "-ll", "-r", target)
    if pyproject.exists():
        bandit_command = _module("bandit", "-c", "pyproject.toml", "-ll", "-r", target)
    if _run_external("bandit", bandit_command, root) != 0:
        return 1
    if _run_external("pip-audit", _module("pip_audit"), root) != 0:
        return 1

    try:
        baseline = secrets.load_baseline(root)
        scan_results = secrets.scan_target(root, _resolve(root, target))
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    new_secrets = secrets.find_new_secrets(scan_results, baseline)
    if new_secrets:
        print("New secrets detected:")
        for secret in new_secrets:
            print(secret)
        return 1
    print("detect-secrets: ok")
    return 0


def _run_external(name: str, command: Sequence[str], root: Path) -> int:
    result = run_command(name, command, root)
    _print_command(result)
    return 0 if result.passed else 1


def _print_command(result: CompletedCommand) -> None:
    print(result.name)
    if result.output:
        print(result.output)


def _module(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def _target_or_default(target: str | None, defaults: tuple[str, ...]) -> str:
    return target or defaults[0]


def _resolve(root: Path, target: str) -> Path:
    path = Path(target)
    return path if path.is_absolute() else root / path
