"""Changed-file detection for incremental checks (`crag check --changed`)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from crag.runner import run_command


def changed_python_files(
    root: Path,
    since: str | None,
    allowed: Sequence[str],
) -> list[str] | None:
    """Return changed + untracked Python files under the allowed paths.

    Returns None when git is unavailable or the root is not a repository.
    """
    if not _is_git_repository(root):
        return None
    base = _resolve_base(root, since)
    if base is None:
        return None
    changed = _git(root, "diff", "--name-only", "--diff-filter=ACMR", base) or ""
    untracked = _git(root, "ls-files", "--others", "--exclude-standard") or ""
    names = [*changed.splitlines(), *untracked.splitlines()]
    return _filter_python_files(root, names, allowed)


def _resolve_base(root: Path, since: str | None) -> str | None:
    if since is None:
        return "HEAD"
    merge_base = _git(root, "merge-base", since, "HEAD")
    return merge_base.strip() if merge_base is not None else None


def _filter_python_files(
    root: Path,
    names: list[str],
    allowed: Sequence[str],
) -> list[str]:
    files: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name.endswith(".py") or name in files:
            continue
        if _is_allowed(name, allowed) and (root / name).exists():
            files.append(name)
    return files


def _is_git_repository(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-inside-work-tree") is not None


def _git(root: Path, *args: str) -> str | None:
    try:
        result = run_command("git", ["git", *args], root)
    except OSError:
        return None
    return result.stdout if result.passed else None


def _is_allowed(name: str, allowed: Sequence[str]) -> bool:
    path = Path(name)
    return any(
        path == Path(prefix) or path.is_relative_to(prefix) for prefix in allowed
    )
