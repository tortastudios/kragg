"""Shared glob matching for repo-relative POSIX paths.

`fnmatchcase` is case-sensitive and deterministic across platforms (no OS
case-folding), and `*` spans `/`. Used by `structure_exclude` (architecture
gate) and the `mutation_include` / `mutation_exclude` scope knobs so the two
conventions cannot drift apart.
"""

from __future__ import annotations

from fnmatch import fnmatchcase


def matches_any(relative: str, patterns: tuple[str, ...]) -> bool:
    """True if the repo-relative POSIX path matches any fnmatch pattern."""
    return any(fnmatchcase(relative, pattern) for pattern in patterns)
