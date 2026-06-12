# AGENTS.md

## Mission

This repository builds `crag`, an opinionated Python guardrails framework and CLI for AI-assisted Python projects. Optimize changes for correctness, safety, and minimal disruption to the public CLI/package behavior.

## Priority Order

When tradeoffs conflict, use this order:

1. Correctness.
2. Data safety.
3. Minimal diff.
4. Existing project conventions.
5. Performance.
6. Elegance.

Do not optimize for elegance by expanding scope. Do not optimize for performance unless the task is performance-related or a measured bottleneck exists.

## Operating Rules

- Do exactly what the user asked.
- Prefer small, local changes.
- Prefer modifying existing functions over adding helper layers when the change is local.
- Preserve existing architecture unless explicitly asked to change it.
- Read nearby code before editing.
- Match existing naming, structure, typing, and error-handling patterns.
- Do not refactor unrelated code.
- Do not rewrite unrelated files.
- Do not reformat untouched files.
- Preserve public APIs and CLI behavior unless the task explicitly requires changing them.
- Do not introduce new abstractions unless they remove duplicated behavior in the changed files.
- Do not introduce new dependencies without explicit user approval.
- When blocked, report the blocker and propose the smallest next step.

## Project Map

- `src/crag/cli.py`: CLI command parsing and command orchestration.
- `src/crag/scaffold.py`: generated project files and initialization logic.
- `src/crag/gates/`: built-in guardrail checks for complexity, secrets, Halstead metrics, and criticality.
- `src/crag/policy.py`: `crag.toml` / `[tool.crag]` policy loading and defaults.
- `src/crag/models.py`: shared result/context data types.
- `src/crag/runner.py`: external command execution wrapper.
- `src/crag/environment.py`: project-interpreter resolution for environment-dependent tools (pytest, mypy, pip-audit, deptry).
- `src/crag/check.py`: gate pipeline (fast/slow tiers, run-all semantics).
- `src/crag/parsers.py`: tool output parsers producing structured violations.
- `src/crag/report.py`: consolidated reports, JSON schema, text rendering, exit codes.
- `src/crag/changes.py`: git-based changed-file detection for `--changed`.
- `src/crag/journal.py`: `.crag/history.jsonl` run journal backing `crag status`.
- `tests/`: focused unit and CLI tests.
- `pyproject.toml`: package metadata, CLI entry point, dependencies, and tool configuration.

Update this section when the repo structure changes.

## Commands

- Install: `uv sync`
- Run CLI: `uv run crag --help`
- Test: `uv run pytest`
- Typecheck: `uv run mypy src tests`
- Lint: `uv run ruff check src tests`
- Format check: `uv run ruff format --check src tests`
- Format: `uv run ruff format src tests`
- Focused guardrail check: `uv run crag check --file <path>`

Use the narrowest relevant command first. Run broader validation before claiming completion when practical.

## Code Standards

- Python target is 3.12.
- Keep strict typing clean; do not weaken types to silence errors.
- Prefer explicit return types at module boundaries and public functions.
- Prefer existing utilities over new abstractions.
- Keep functions small, but do not split code just for aesthetics.
- Handle errors explicitly. Do not hide failures.
- Keep generated scaffold content readable and minimal.
- Use Mermaid only for execution flow, ownership boundaries, or data flow, and keep diagrams small.

## Testing Rules

- Add or update tests for changed behavior.
- Prefer focused tests near the changed code.
- Run the narrowest relevant test first.
- Run `uv run pytest`, `uv run ruff check src tests`, and `uv run mypy src tests` before claiming completion when practical.
- Do not delete failing tests unless they are obsolete and the reason is explained.
- If tests cannot be run, state exactly why.

## Stop Conditions

Stop and ask before:

- adding a production dependency,
- changing public CLI commands or importable public APIs,
- changing generated CI, deployment, or secrets handling,
- changing authentication or authorization behavior,
- changing billing or payment behavior,
- changing database schema or migrations,
- deleting data,
- making broad architectural changes,
- replacing working code with a new pattern just because it is cleaner.

Before changing database schema in any future project that has one, inspect existing migrations and update tests. After changing API behavior in any future API layer, update or add request/response tests.

## Do Not

- Do not rewrite unrelated files.
- Do not rename symbols for style only.
- Do not reformat untouched files.
- Do not weaken types to silence errors.
- Do not add caching, retries, queues, or concurrency unless requested.
- Do not replace working code with a new pattern just because it is cleaner.
- Do not claim success without validation.

## Definition of Done

A task is complete when:

- the requested behavior is implemented,
- relevant tests are added or updated,
- validation commands have been run when practical,
- the final response lists changed files, validation results, and any remaining risks.
