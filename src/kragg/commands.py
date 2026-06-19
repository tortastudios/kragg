"""Command handlers for the kragg CLI.

`cli.py` owns argument parsing and dispatch; this module holds the one
function behind each subcommand plus their shared helpers, so neither file
grows past a single concern.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from kragg import (
    brief,
    coverage,
    environment,
    journal,
    mapping,
    mutation,
    report,
    spec,
)
from kragg.catalog import build_check_gates, build_security_gates
from kragg.changes import changed_python_files
from kragg.check import GateSpec, run_gates
from kragg.environment import ProjectEnvironment, resolve_project_environment
from kragg.gates import criticality
from kragg.hooks import run_claude_hook
from kragg.models import CompletedCommand
from kragg.policy import KraggPolicy, load_policy
from kragg.report import (
    EXIT_ENVIRONMENT,
    EXIT_GATE_FAILURES,
    EXIT_OK,
    EXIT_USAGE,
)
from kragg.runner import run_command
from kragg.scaffold import create_new_project, generate_module, initialize_project


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
    print("  uv run kragg check")
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
    print("Run `uv run kragg check` after filling in the slots.")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    written = initialize_project(root)
    print(f"Initialized kragg in {root}")
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
    policy: KraggPolicy,
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
    policy: KraggPolicy,
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
        criticality.write_json(profiles, root / ".kragg" / "criticality.json")
        print(f"Wrote {output} and .kragg/criticality.json")
    else:
        criticality.print_table(profiles)
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    root = Path.cwd()
    text = brief.build_brief(root, load_policy(root), args.since)
    if text is None:
        print("not a git repository (required for brief)", file=sys.stderr)
        return EXIT_ENVIRONMENT
    print(text, end="")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    root = Path.cwd()
    lines = mapping.build_map(root, load_policy(root))
    if not lines:
        print("no public symbols found")
        return 0
    print("\n".join(lines))
    if args.write:
        output = root / ".kragg" / "map.md"
        mapping.write_map(lines, output)
        print(f"Wrote {output}")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    del args
    root = Path.cwd()
    policy = load_policy(root)
    if coverage.read_report(root) is None:
        print("no coverage data (run `kragg check` first)")
        return 0
    for line in coverage.render_gaps(coverage.critical_gaps(root, policy.source_paths)):
        print(line)
    return 0


def cmd_mutation(args: argparse.Namespace) -> int:
    root = Path.cwd()
    policy = load_policy(root)
    env = _project_environment(root)
    if env is None:
        return EXIT_ENVIRONMENT
    targets = mutation.select_targets(root, policy, args.since, args.mutate_all)
    if targets is None:
        print("not a git repository (use --all)", file=sys.stderr)
        return EXIT_USAGE
    if not targets:
        print("no changed critical files to mutate")
        return EXIT_OK
    if not mutation.cosmic_ray_available(env):
        print("cosmic-ray is not installed in the project environment")
        print(environment.remediation("cosmic_ray"))
        return EXIT_ENVIRONMENT
    result = mutation.run_mutation(root, env, policy, targets)
    return _report_mutation(root, result, args.update_baseline)


def _report_mutation(
    root: Path,
    result: mutation.MutationReport,
    update_baseline: bool,
) -> int:
    if result.error is not None:
        print(result.error, file=sys.stderr)
        return EXIT_ENVIRONMENT
    if update_baseline:
        count = mutation.write_baseline(root, result.survivors)
        print(f"baselined {count} surviving mutants in {mutation.BASELINE_RELATIVE}")
        return EXIT_OK
    baseline = mutation.load_baseline(root)
    survivors = mutation.filter_baselined(result.survivors, baseline)
    for line in mutation.render_survivors(survivors):
        print(line)
    return EXIT_GATE_FAILURES if survivors else EXIT_OK


def cmd_spec(args: argparse.Namespace) -> int:
    del args
    root = Path.cwd()
    policy = load_policy(root)
    for line in spec.render_spec(spec.build_spec(root, policy.test_paths)):
        print(line)
    rows = spec.property_coverage(root, policy.source_paths, policy.test_paths)
    for line in spec.render_property_coverage(rows):
        print(line)
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
        print("no recorded runs (run `kragg check` first)")
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
    print(f"kragg interpreter: {sys.executable}")
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
    kragg_prefix = Path(sys.prefix).resolve()
    if env.python is not None and env.python.parent.parent.resolve() == kragg_prefix:
        print("note: kragg runs inside the project environment (dev-dependency mode)")
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
