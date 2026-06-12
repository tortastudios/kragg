# crag

`crag` is an opinionated guardrails framework for AI-assisted Python projects.
It is agent-first: coding agents (Claude Code, Codex, Cursor, Gemini CLI, …)
are the primary users, running check → fix loops. crag gives them one command,
structured results, meaningful exit codes, and copy-pasteable fixes.

## Install modes

**Dev dependency (recommended).** crag runs inside the project environment, so
every tool sees the project's packages:

```bash
uv add --dev crag
uv run crag check
```

**Global tool (pipx / uv tool).** crag runs from its own environment, but
environment-dependent gates (pytest, mypy, pip-audit, deptry) are always
executed on the *project's* interpreter, resolved in this order:

1. `CRAG_PROJECT_PYTHON` environment variable (explicit override)
2. `<project>/.venv`
3. an active `VIRTUAL_ENV` (ignored when it is crag's own environment)
4. `uv run --project <project>` as a fallback

If no project environment exists, those gates fail loudly with the exact fix
(`uv sync`, `uv add --dev mypy`, …) instead of silently running in the wrong
environment. `crag doctor` shows which interpreter was resolved and which
tools are missing.

## Commands

```bash
crag new my-app --kind cli   # layered skeleton (cli | api | worker) + uv sync
crag gen module payments     # service/domain/test slots in the layout
crag init .                  # add guardrails to an existing project
crag check                   # all gates, consolidated report
crag check --changed         # only files changed in git (cheap inner loop)
crag check --since main      # changed vs merge-base with a ref
crag check --file src/foo.py --file src/bar.py
crag check --format json     # stable machine-readable schema
crag fix                     # auto-fix formatting and safe lint
crag map                     # public symbol inventory (what already exists)
crag brief                   # reviewable digest of the change set
crag security
crag audit
crag criticality --write     # call-graph risk -> CRITICALITY.md + .crag/
crag status                  # what failed last run, without re-running
crag hook claude             # harness hook adapter (reads hook JSON on stdin)
crag doctor                  # environment diagnostics with exact fixes
crag policy show
```

## Gates

Fast (always all run): ruff, mypy, radon-cc, radon-mi, halstead,
type-complexity, **boundaries** (layered import contract from
`[tool.crag] layers`), **structure** (file/symbol budgets),
**critical-tests** (critical functions cannot change without test changes),
**test-quality** (no assertion-free tests; critical functions must be
referenced by tests), bandit, detect-secrets.
Slow (skipped while fast gates fail): pytest+coverage, pip-audit.

## Agent-native design

Agents drift where they have freedom, so the scaffold removes the freedom:
every kind ships one layered layout (`entrypoints/` → `services/` →
`domain/`) with the `boundaries` gate enforcing dependency direction from
the first commit, and `crag gen module` creates new code in the one place
it belongs. The tool holds the memory the agent lacks: `crag map` is the
inventory of what exists (injected at session start so nothing gets
reinvented), `.crag/history.jsonl` remembers runs, `CRITICALITY.md`
remembers risk, and `crag brief` renders the change set legible to the
human reviewer.

## Agent loop design

- `crag check` runs **all static gates** and reports every failure in one run
  (one loop iteration instead of one per gate). Slow gates (pytest, pip-audit)
  are skipped while static gates fail; `--fail-fast` and `--all` override.
- Output is token-efficient: violations are deduplicated, capped per gate
  (`--max-violations`, policy `max_violations_per_gate`), and reported as
  `file:line` pointers with fix hints instead of raw tool dumps.
- Exit codes are branchable without parsing: `0` pass, `1` gate failures,
  `2` usage error, `3` environment broken.
- Every run appends a slim line to `.crag/history.jsonl`; `crag status` answers
  "what failed last run" for a few tokens.
- Scaffolding emits `AGENTS.md` as the canonical agent contract (read by
  Codex, Cursor, Gemini CLI, and Claude Code via a `CLAUDE.md` pointer), plus
  hooks that run `crag check --changed` after edits.

## Configuration

Configure crag in `pyproject.toml` under `[tool.crag]`, or in a standalone
`crag.toml` (top-level keys, takes precedence when present):

```toml
[tool.crag]
profile = "strict-ai-python"
source_paths = ["src"]
test_paths = ["tests"]
coverage_fail_under = 80
type_max_nesting_depth = 2
type_max_length = 40
max_violations_per_gate = 25
```

## V1 scope

`crag` models agentic workflow support as policy packs, not as an LLM runtime.
A policy pack defines the gates, thresholds, generated agent instructions, and
project wrappers that keep AI-authored Python code inside known constraints.

The default policy pack is `strict-ai-python`.
