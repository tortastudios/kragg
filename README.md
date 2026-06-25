# kragg

`kragg` is an opinionated guardrails framework for AI-assisted Python projects.
It is agent-first: coding agents (Claude Code, Codex, Cursor, Gemini CLI, …)
are the primary users, running check → fix loops. kragg gives them one command,
structured results, meaningful exit codes, and copy-pasteable fixes.

## Install modes

**Dev dependency (recommended).** kragg runs inside the project environment, so
every tool sees the project's packages:

```bash
uv add --dev kragg
uv run kragg check
```

**Global tool (pipx / uv tool).** kragg runs from its own environment, but
environment-dependent gates (pytest, mypy, pip-audit, deptry) are always
executed on the *project's* interpreter, resolved in this order:

1. `KRAGG_PROJECT_PYTHON` environment variable (explicit override)
2. `<project>/.venv`
3. an active `VIRTUAL_ENV` (ignored when it is kragg's own environment)
4. `uv run --project <project>` as a fallback

If no project environment exists, those gates fail loudly with the exact fix
(`uv sync`, `uv add --dev mypy`, …) instead of silently running in the wrong
environment. `kragg doctor` shows which interpreter was resolved and which
tools are missing.

## Commands

```bash
kragg new my-app --kind cli   # layered skeleton (cli | api | worker) + uv sync
kragg gen module payments     # service/domain/test slots in the layout
kragg init .                  # add guardrails to an existing project
kragg check                   # all gates, consolidated report
kragg check --changed         # only files changed in git (cheap inner loop)
kragg check --since main      # changed vs merge-base with a ref
kragg check --file src/foo.py --file src/bar.py
kragg check --format json     # stable machine-readable schema
kragg fix                     # auto-fix formatting and safe lint
kragg map                     # public symbol inventory (what already exists)
kragg spec                    # test suite rendered as a readable spec tree
kragg coverage                # uncovered lines in critical functions (ranked)
kragg mutation                # mutation-test changed critical files (cosmic-ray)
kragg mutation --all          # mutation-test every critical file
kragg mutation --update-baseline  # accept current survivors (equivalent mutants)
kragg brief                   # reviewable digest of the change set
kragg security
kragg audit
kragg criticality --write     # call-graph risk -> CRITICALITY.md + .kragg/
kragg status                  # what failed last run, without re-running
kragg flaky                   # gates that flipped pass/fail on an unchanged commit
kragg flaky --rerun 20        # re-run the suite N times, rank tests by failure ratio
kragg hook claude             # harness hook adapter (reads hook JSON on stdin)
kragg doctor                  # environment diagnostics with exact fixes
kragg policy show
```

## Gates

Fast (always all run): ruff, mypy, **typing-strictness** (the project's mypy
config actually meets the strict floor — no missing/loosened flags, no
`ignore_errors`, no bare `# type: ignore`; makes `strict-ai-python` a verified
contract instead of a label), radon-cc, radon-mi, halstead, type-complexity,
**boundaries** (layered import contract from `[tool.kragg] layers`),
**structure** (file/symbol budgets), **nullable-default** (arithmetic on
`.get(key, default)` results, which crash when the key is present-but-null),
**critical-tests** (critical functions cannot change without test changes),
**test-quality** (no assertion-free tests; critical functions must be
referenced by tests), bandit, detect-secrets.
Slow (skipped while fast gates fail): pytest+coverage, **critical-coverage**
(public critical functions must have no uncovered lines), pip-audit.

## Test depth

Green checkmarks are easy to fake, so kragg looks past them with layered,
mostly-deterministic signals — each a harder-to-game answer to "do the tests
actually defend behavior":

- **what's run** — `kragg coverage` surfaces uncovered lines in critical
  functions, ranked by fan-in, instead of a gameable global percentage; the
  `critical-coverage` gate fails on any uncovered line in a critical function.
- **what's defended** — `kragg mutation` runs cosmic-ray over the changed
  critical files (the criticality graph and git diff keep it cheap) and reports
  surviving mutants as `file:line` fixes. Accept equivalent mutants with
  `kragg mutation --update-baseline`.
- **what's claimed** — `kragg spec` renders test names and docstrings as a
  documentation tree and flags critical functions that have only example-based
  tests (property-based tests, via Hypothesis, kill more mutants).
- **what's trustworthy** — `kragg flaky` mines the run journal for gates that
  flipped on an unchanged commit; `--rerun N` re-runs the suite and ranks tests
  by failure ratio (for cron/CI, never the inner loop).

Mutation and active flaky runs are deliberately outside `kragg check`: they are
on-demand or CI surfaces, not inner-loop gates.

`kragg mutation` runs cosmic-ray on the project interpreter, so add it to the
project being checked (`uv add --dev cosmic-ray`); kragg prints the exact
command if it is missing. Property-based tests use Hypothesis
(`uv add --dev hypothesis`). Mutation needs an editable/source install so it
mutates the code the tests import.

## Agent-native design

Agents drift where they have freedom, so the scaffold removes the freedom:
every kind ships one layered layout (`entrypoints/` → `services/` →
`domain/`) with the `boundaries` gate enforcing dependency direction from
the first commit, and `kragg gen module` creates new code in the one place
it belongs. The tool holds the memory the agent lacks: `kragg map` is the
inventory of what exists (injected at session start so nothing gets
reinvented), `.kragg/history.jsonl` remembers runs, `CRITICALITY.md`
remembers risk, and `kragg brief` renders the change set legible to the
human reviewer.

## Agent loop design

- `kragg check` runs **all static gates** and reports every failure in one run
  (one loop iteration instead of one per gate). Slow gates (pytest, pip-audit)
  are skipped while static gates fail; `--fail-fast` and `--all` override.
- Output is token-efficient: violations are deduplicated, capped per gate
  (`--max-violations`, policy `max_violations_per_gate`), and reported as
  `file:line` pointers with fix hints instead of raw tool dumps.
- Exit codes are branchable without parsing: `0` pass, `1` gate failures,
  `2` usage error, `3` environment broken.
- Every run appends a slim line to `.kragg/history.jsonl`; `kragg status` answers
  "what failed last run" for a few tokens.
- Scaffolding emits `AGENTS.md` as the canonical agent contract (read by
  Codex, Cursor, Gemini CLI, and Claude Code via a `CLAUDE.md` pointer), plus
  hooks that run `kragg check --changed` after edits.

## Configuration

Configure kragg in `pyproject.toml` under `[tool.kragg]`, or in a standalone
`kragg.toml` (top-level keys, takes precedence when present):

```toml
[tool.kragg]
profile = "strict-ai-python"
source_paths = ["src"]
test_paths = ["tests"]
coverage_fail_under = 80
type_max_nesting_depth = 2
type_max_length = 40
max_violations_per_gate = 25
max_file_lines = 500
max_public_symbols = 20
structure_exclude = [
    # flat or generated files that legitimately exceed the budgets;
    # document why each entry earns its exemption
    "src/app/icons.py",  # 4k lines of generated base64 icon data
    "*_pb2.py",          # protobuf-generated modules, any depth
]
mutation_include = [
    # explicit mutation targets (globs); REPLACES criticality as the base set,
    # to reach high-value logic that modest fan-in keeps out of the graph
    "src/billing/entitlement_engine.py",
    "src/billing/*.py",
]
mutation_exclude = ["src/observability.py"]  # fail-safe glue; mutants mostly equivalent
```

`structure_exclude` exempts matching files from the **structure** gate's
file- and symbol-budgets only — they stay subject to every other gate, so
the cap stays meaningful repo-wide. Reach for it after splitting fails:
genuinely flat data, vendored code, or generated modules you can't annotate.
Patterns are repo-root-relative POSIX paths matched with `fnmatch`
(case-sensitive); `*` matches any characters including `/`, so
`src/generated/*` exempts that whole subtree — scope patterns narrowly.

`mutation_include` / `mutation_exclude` scope `kragg mutation` (same glob
convention). Mutation scope is its own axis, not just criticality: by default
it targets the files defining any critical function — public *or* private (it
mutates whole modules, so a high-risk private boundary like `Client._call`
still counts). `mutation_include` **replaces** that with an explicit set —
reach for it to mutate high-value logic (access checks, billing math) that
modest fan-in keeps out of the criticality graph. `mutation_exclude` drops
files even when critical: fail-safe glue like telemetry, where `try/except:
return` swallowing makes most mutants equivalent, so a high survival rate there
is expected, not a test gap. Ad-hoc override: `kragg mutation --all --path
"src/billing/*.py"` (repeatable).

## V1 scope

`kragg` models agentic workflow support as policy packs, not as an LLM runtime.
A policy pack defines the gates, thresholds, generated agent instructions, and
project wrappers that keep AI-authored Python code inside known constraints.

The default policy pack is `strict-ai-python`.
