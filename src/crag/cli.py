from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from crag import environment, journal, mapping, report, templates
from crag.changes import changed_python_files
from crag.check import GateSpec, build_check_gates, build_security_gates, run_gates
from crag.environment import ProjectEnvironment, resolve_project_environment
from crag.gates import criticality
from crag.hooks import run_claude_hook
from crag.models import CompletedCommand
from crag.policy import CragPolicy, load_policy
from crag.report import EXIT_ENVIRONMENT, EXIT_OK, EXIT_USAGE
from crag.runner import run_command
from crag.scaffold import create_new_project, generate_module, initialize_project


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
        return EXIT_USAGE
    return handler(args)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(prog="crag")
    subparsers = parser.add_subparsers(dest="command")

    new_parser = subparsers.add_parser("new", help="create a new project")
    new_parser.add_argument("name")
    new_parser.add_argument("--kind", choices=templates.KINDS, default="cli")
    new_parser.add_argument("--no-sync", action="store_true")
    new_parser.set_defaults(handler=cmd_new)

    gen_parser = subparsers.add_parser("gen", help="generate code into the layout")
    gen_parser.add_argument("generator", choices=("module",))
    gen_parser.add_argument("name")
    gen_parser.set_defaults(handler=cmd_gen)

    init_parser = subparsers.add_parser("init", help="add crag to a project")
    init_parser.add_argument("path", nargs="?", default=".")
    init_parser.set_defaults(handler=cmd_init)

    check_parser = subparsers.add_parser("check", help="run quality gates")
    _add_report_arguments(check_parser)
    check_parser.add_argument("--changed", action="store_true")
    check_parser.add_argument("--since", default=None)
    check_parser.add_argument("--fail-fast", dest="fail_fast", action="store_true")
    check_parser.add_argument("--all", dest="run_all", action="store_true")
    check_parser.set_defaults(handler=cmd_check)

    fix_parser = subparsers.add_parser("fix", help="format and safely fix lint")
    fix_parser.add_argument("--file", dest="targets", action="append")
    fix_parser.set_defaults(handler=cmd_fix)

    security_parser = subparsers.add_parser("security", help="run security gates")
    _add_report_arguments(security_parser)
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

    map_parser = subparsers.add_parser("map", help="public symbol inventory")
    map_parser.add_argument("--write", action="store_true")
    map_parser.set_defaults(handler=cmd_map)

    hook_parser = subparsers.add_parser(
        "hook",
        help="harness hook adapter (reads hook JSON from stdin)",
    )
    hook_parser.add_argument("harness", choices=("claude",))
    hook_parser.set_defaults(handler=cmd_hook)

    status_parser = subparsers.add_parser("status", help="show recent run history")
    status_parser.add_argument("--format", choices=("text", "json"), default="text")
    status_parser.add_argument("--last", type=int, default=10)
    status_parser.set_defaults(handler=cmd_status)

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


def _add_report_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file", dest="targets", action="append")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--max-violations", dest="max_violations", type=int)
    parser.add_argument("--no-journal", dest="no_journal", action="store_true")


def cmd_new(args: argparse.Namespace) -> int:
    target = Path(args.name).resolve()
    try:
        written = create_new_project(target, target.name, kind=args.kind)
    except (FileExistsError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Created {target}")
    print(f"Wrote {len(written)} files")
    if not args.no_sync:
        _sync_new_project(target)
    print("Next steps:")
    print(f"  cd {args.name}")
    print("  uv run crag check")
    return 0


def _sync_new_project(target: Path) -> None:
    if shutil.which("uv") is None:
        print("uv not found; create the environment with `uv sync`")
        return
    result = run_command("uv sync", ["uv", "sync"], target)
    if result.passed:
        print("Synced project environment (.venv)")
    else:
        print("uv sync failed; run it manually after fixing:", file=sys.stderr)
        print(result.output, file=sys.stderr)


def cmd_gen(args: argparse.Namespace) -> int:
    del args.generator  # only "module" exists today
    root = Path.cwd()
    try:
        written = generate_module(root, args.name)
    except (FileExistsError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    for path in written:
        print(f"Wrote {path.relative_to(root)}")
    print("Run `uv run crag check` after filling in the slots.")
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
    resolved = _check_targets(args, root, policy)
    if resolved is None:
        return EXIT_ENVIRONMENT
    targets, mode = resolved
    if not targets:
        print("no changed Python files")
        return EXIT_OK
    env = _project_environment(root)
    if env is None:
        return EXIT_ENVIRONMENT
    specs = build_check_gates(root, policy, env, targets, incremental=mode != "full")
    return _run_pipeline("check", args, root, policy, specs, targets, mode)


def cmd_security(args: argparse.Namespace) -> int:
    root = Path.cwd()
    policy = load_policy(root)
    targets = tuple(args.targets) if args.targets else (policy.source_paths[0],)
    mode = "file" if args.targets else "full"
    env = _project_environment(root)
    if env is None:
        return EXIT_ENVIRONMENT
    specs = build_security_gates(root, env, targets, incremental=mode != "full")
    return _run_pipeline("security", args, root, policy, specs, targets, mode)


def _check_targets(
    args: argparse.Namespace,
    root: Path,
    policy: CragPolicy,
) -> tuple[tuple[str, ...], str] | None:
    if args.changed or args.since:
        allowed = (*policy.source_paths, *policy.test_paths)
        files = changed_python_files(root, args.since, allowed)
        if files is None:
            print(
                "not a git repository (required for --changed/--since)",
                file=sys.stderr,
            )
            return None
        return tuple(files), "changed"
    if args.targets:
        return tuple(args.targets), "file"
    return (policy.source_paths[0],), "full"


def _project_environment(root: Path) -> ProjectEnvironment | None:
    try:
        return resolve_project_environment(root)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return None


def _run_pipeline(
    command: str,
    args: argparse.Namespace,
    root: Path,
    policy: CragPolicy,
    specs: list[GateSpec],
    targets: tuple[str, ...],
    mode: str,
) -> int:
    started_at = report.utc_now()
    results = run_gates(
        specs,
        fail_fast=getattr(args, "fail_fast", False),
        force_slow=getattr(args, "run_all", False),
    )
    max_violations = args.max_violations or policy.max_violations_per_gate
    built = report.build_report(
        command=command,
        mode=mode,
        targets=targets,
        results=results,
        max_violations=max_violations,
        started_at=started_at,
        git_sha=report.git_sha(root),
    )
    if args.format == "json":
        print(report.render_json(built))
    else:
        print(report.render_text(built))
    if not args.no_journal:
        journal.append_run(root, report.to_payload(built))
    return built.exit_code


def cmd_fix(args: argparse.Namespace) -> int:
    root = Path.cwd()
    policy = load_policy(root)
    targets = tuple(args.targets) if args.targets else (policy.source_paths[0],)
    for command_name, command in (
        ("ruff format", _module("ruff", "format", *targets)),
        ("ruff fix", _module("ruff", "check", "--fix", *targets)),
    ):
        if _run_external(command_name, command, root) != 0:
            return 1
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    del args
    root = Path.cwd()
    policy = load_policy(root)
    source = policy.source_paths[0]
    if cmd_criticality(argparse.Namespace(write=True, path=source)) != 0:
        return 1
    if _run_external("vulture", _module("vulture", source), root) != 0:
        return 1
    env = _project_environment(root)
    if env is None:
        return EXIT_ENVIRONMENT
    if _run_project_external("deptry", env, root, "deptry", source) != 0:
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
        criticality.write_json(profiles, root / ".crag" / "criticality.json")
        print(f"Wrote {output} and .crag/criticality.json")
    else:
        criticality.print_table(profiles)
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    root = Path.cwd()
    lines = mapping.build_map(root, load_policy(root))
    if not lines:
        print("no public symbols found")
        return 0
    print("\n".join(lines))
    if args.write:
        output = root / ".crag" / "map.md"
        mapping.write_map(lines, output)
        print(f"Wrote {output}")
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    del args  # only the claude protocol exists today
    return run_claude_hook(sys.stdin.read(), Path.cwd())


def cmd_status(args: argparse.Namespace) -> int:
    root = Path.cwd()
    runs = journal.read_runs(root, args.last)
    if args.format == "json":
        last_run = runs[-1] if runs else None
        print(json.dumps({"last_run": last_run, "runs": runs}, indent=1))
        return 0
    if not runs:
        print("no recorded runs (run `crag check` first)")
        return 0
    for line in journal.render_status_lines(runs):
        print(line)
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
    if not _doctor_environment(root):
        failed = True
    return 1 if failed else 0


def _doctor_environment(root: Path) -> bool:
    print(f"crag interpreter: {sys.executable}")
    env = _project_environment(root)
    if env is None:
        return False
    if not env.found:
        print(
            "project interpreter: MISSING -> fix: uv sync "
            f"(or set {environment.ENV_VAR}=/path/to/python)"
        )
        return False
    print(f"project interpreter: {env.describe()}")
    crag_prefix = Path(sys.prefix).resolve()
    if env.python is not None and env.python.parent.parent.resolve() == crag_prefix:
        print("note: crag runs inside the project environment (dev-dependency mode)")
    if not (root / "pyproject.toml").exists():
        print("project env tools: skipped (no pyproject.toml)")
        return True
    return _doctor_project_tools(env)


def _doctor_project_tools(env: ProjectEnvironment) -> bool:
    probed = environment.probe_modules(env, environment.PROJECT_MODULES)
    if probed is None:
        print("project env tools: could not probe (interpreter failed to run)")
        return False
    print("project env tools:")
    ok = True
    for module in environment.PROJECT_MODULES:
        if probed.get(module, False):
            print(f"  {module}: ok")
        else:
            print(f"  {module}: MISSING -> {environment.remediation(module)}")
            ok = False
    return ok


def cmd_policy_show(args: argparse.Namespace) -> int:
    del args
    policy = load_policy(Path.cwd())
    print(json.dumps(policy.as_dict(), indent=2, sort_keys=True))
    return 0


def _run_external(name: str, command: Sequence[str], root: Path) -> int:
    result = run_command(name, command, root)
    _print_command(result)
    return 0 if result.passed else 1


def _run_project_external(
    name: str,
    env: ProjectEnvironment,
    root: Path,
    module: str,
    *args: str,
) -> int:
    result = run_command(name, env.module_command(module, *args), root)
    _print_command(result)
    if result.passed:
        return 0
    missing = environment.missing_module(result)
    if missing == module:
        print(environment.remediation(missing))
        return EXIT_ENVIRONMENT
    return 1


def _print_command(result: CompletedCommand) -> None:
    print(result.name)
    if result.output:
        print(result.output)


def _module(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]
