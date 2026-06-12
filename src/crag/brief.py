"""Change brief: a human-reviewable digest of the working-tree change set.

A vibe-coded change is sane when a reviewer can grasp it in minutes. The
brief groups changed files by area, names the critical functions touched,
and reports the last gate run — markdown ready for a PR description.
"""

from __future__ import annotations

from pathlib import Path

from crag import journal
from crag.gates.critical_tests import critical_in_files
from crag.policy import CragPolicy
from crag.runner import run_command


def build_brief(root: Path, policy: CragPolicy, since: str | None) -> str | None:
    """Build the markdown brief; None when git is unavailable."""
    base = _resolve_base(root, since)
    if base is None:
        return None
    changed = _changed_files(root, base)
    if changed is None:
        return None
    lines = ["# Change brief", ""]
    lines.append(_stats_line(root, base, changed, since))
    lines.append("")
    lines.extend(_grouped_sections(changed, policy))
    lines.extend(_critical_section(root, policy, changed))
    lines.extend(_gate_section(root))
    return "\n".join(lines).rstrip() + "\n"


def _resolve_base(root: Path, since: str | None) -> str | None:
    if since is None:
        return "HEAD"
    merge_base = _git_lines(root, "merge-base", since, "HEAD")
    return merge_base[0].strip() if merge_base else None


def _changed_files(root: Path, base: str) -> list[str] | None:
    if _git_lines(root, "rev-parse", "--is-inside-work-tree") is None:
        return None
    changed = _git_lines(root, "diff", "--name-only", "--diff-filter=ACMR", base)
    untracked = _git_lines(root, "ls-files", "--others", "--exclude-standard")
    files: list[str] = []
    for raw in [*(changed or []), *(untracked or [])]:
        name = raw.strip()
        if name and not name.startswith(".crag/") and name not in files:
            files.append(name)
    return files


def _stats_line(
    root: Path,
    base: str,
    changed: list[str],
    since: str | None,
) -> str:
    added = deleted = 0
    for line in _git_lines(root, "diff", "--numstat", base) or []:
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0])
            deleted += int(parts[1])
    against = since or "HEAD"
    return f"{len(changed)} files changed (+{added} / -{deleted}) vs {against}"


def _grouped_sections(changed: list[str], policy: CragPolicy) -> list[str]:
    groups: dict[str, list[str]] = {"Source": [], "Tests": [], "Other": []}
    for name in changed:
        groups[_area(name, policy)].append(name)
    lines: list[str] = []
    for title in ("Source", "Tests", "Other"):
        if groups[title]:
            lines.append(f"## {title}")
            lines.extend(f"- {name}" for name in groups[title])
            lines.append("")
    return lines


def _area(name: str, policy: CragPolicy) -> str:
    path = Path(name)
    if any(path.is_relative_to(prefix) for prefix in policy.source_paths):
        return "Source"
    if any(path.is_relative_to(prefix) for prefix in policy.test_paths):
        return "Tests"
    return "Other"


def _critical_section(
    root: Path,
    policy: CragPolicy,
    changed: list[str],
) -> list[str]:
    python_files = [name for name in changed if name.endswith(".py")]
    touched = critical_in_files(root, policy.source_paths, python_files)
    lines = ["## Critical functions touched"]
    if touched:
        lines.extend(
            f"- `{qualname}` (fan-in {fan_in}) in {file}"
            for qualname, fan_in, file in touched
        )
    else:
        lines.append("none")
    lines.append("")
    return lines


def _gate_section(root: Path) -> list[str]:
    runs = journal.read_runs(root, 10)
    lines = ["## Last gate run"]
    if runs:
        lines.extend(journal.render_status_lines(runs))
    else:
        lines.append("no recorded runs (run `uv run crag check`)")
    return lines


def _git_lines(root: Path, *args: str) -> list[str] | None:
    try:
        result = run_command("git", ["git", *args], root)
    except OSError:
        return None
    return result.stdout.splitlines() if result.passed else None
