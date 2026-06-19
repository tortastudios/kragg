from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import cast

from kragg import commands, templates
from kragg.report import EXIT_USAGE


def main(argv: Sequence[str] | None = None) -> int:
    """Run the kragg command-line interface."""
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
    parser = argparse.ArgumentParser(prog="kragg")
    subparsers = parser.add_subparsers(dest="command")

    new_parser = subparsers.add_parser("new", help="create a new project")
    new_parser.add_argument("name")
    new_parser.add_argument("--kind", choices=templates.KINDS, default="cli")
    new_parser.add_argument("--no-sync", action="store_true")
    new_parser.set_defaults(handler=commands.cmd_new)

    gen_parser = subparsers.add_parser("gen", help="generate code into the layout")
    gen_parser.add_argument("generator", choices=("module",))
    gen_parser.add_argument("name")
    gen_parser.set_defaults(handler=commands.cmd_gen)

    init_parser = subparsers.add_parser("init", help="add kragg to a project")
    init_parser.add_argument("path", nargs="?", default=".")
    init_parser.set_defaults(handler=commands.cmd_init)

    check_parser = subparsers.add_parser("check", help="run quality gates")
    _add_report_arguments(check_parser)
    check_parser.add_argument("--changed", action="store_true")
    check_parser.add_argument("--since", default=None)
    check_parser.add_argument("--fail-fast", dest="fail_fast", action="store_true")
    check_parser.add_argument("--all", dest="run_all", action="store_true")
    check_parser.set_defaults(handler=commands.cmd_check)

    fix_parser = subparsers.add_parser("fix", help="format and safely fix lint")
    fix_parser.add_argument("--file", dest="targets", action="append")
    fix_parser.set_defaults(handler=commands.cmd_fix)

    security_parser = subparsers.add_parser("security", help="run security gates")
    _add_report_arguments(security_parser)
    security_parser.set_defaults(handler=commands.cmd_security)

    audit_parser = subparsers.add_parser("audit", help="run architecture audit")
    audit_parser.set_defaults(handler=commands.cmd_audit)

    criticality_parser = subparsers.add_parser(
        "criticality",
        help="analyze call-graph criticality",
    )
    criticality_parser.add_argument("--write", action="store_true")
    criticality_parser.add_argument("--path", default=None)
    criticality_parser.set_defaults(handler=commands.cmd_criticality)

    brief_parser = subparsers.add_parser("brief", help="reviewable change digest")
    brief_parser.add_argument("--since", default=None)
    brief_parser.set_defaults(handler=commands.cmd_brief)

    map_parser = subparsers.add_parser("map", help="public symbol inventory")
    map_parser.add_argument("--write", action="store_true")
    map_parser.set_defaults(handler=commands.cmd_map)

    coverage_parser = subparsers.add_parser(
        "coverage",
        help="critical-function coverage gaps from the last check",
    )
    coverage_parser.set_defaults(handler=commands.cmd_coverage)

    mutation_parser = subparsers.add_parser(
        "mutation",
        help="mutation-test changed critical files (cosmic-ray)",
    )
    mutation_parser.add_argument("--since", default=None)
    mutation_parser.add_argument("--all", dest="mutate_all", action="store_true")
    mutation_parser.add_argument(
        "--update-baseline",
        dest="update_baseline",
        action="store_true",
        help="record current survivors as accepted (equivalent) mutants",
    )
    mutation_parser.set_defaults(handler=commands.cmd_mutation)

    spec_parser = subparsers.add_parser(
        "spec",
        help="render the test suite as a readable spec tree",
    )
    spec_parser.set_defaults(handler=commands.cmd_spec)

    hook_parser = subparsers.add_parser(
        "hook",
        help="harness hook adapter (reads hook JSON from stdin)",
    )
    hook_parser.add_argument("harness", choices=("claude",))
    hook_parser.set_defaults(handler=commands.cmd_hook)

    status_parser = subparsers.add_parser("status", help="show recent run history")
    status_parser.add_argument("--format", choices=("text", "json"), default="text")
    status_parser.add_argument("--last", type=int, default=10)
    status_parser.set_defaults(handler=commands.cmd_status)

    doctor_parser = subparsers.add_parser("doctor", help="verify project setup")
    doctor_parser.set_defaults(handler=commands.cmd_doctor)

    policy_parser = subparsers.add_parser("policy", help="inspect policies")
    policy_subparsers = policy_parser.add_subparsers(
        dest="policy_command",
        required=True,
    )
    policy_show = policy_subparsers.add_parser("show", help="show active policy")
    policy_show.set_defaults(handler=commands.cmd_policy_show)

    return parser


def _add_report_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file", dest="targets", action="append")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--max-violations", dest="max_violations", type=int)
    parser.add_argument("--no-journal", dest="no_journal", action="store_true")
