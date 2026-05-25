# crag

`crag` is an opinionated guardrails framework for AI-assisted Python projects.
It packages the quality, security, and architecture checks from the starter
project into one installable CLI and one import package.

## Install

```bash
pipx install crag
```

For project-local checks, add `crag` as a dev dependency and run it through the
project environment:

```bash
uv add --dev crag
uv run crag check
```

## Commands

```bash
crag new my-project
crag init .
crag check
crag check --file src/foo.py
crag fix
crag security
crag audit
crag criticality --write
crag doctor
crag policy show
```

## V1 scope

`crag` models agentic workflow support as policy packs, not as an LLM runtime.
A policy pack defines the gates, thresholds, generated agent instructions, and
project wrappers that keep AI-authored Python code inside known constraints.

The default policy pack is `strict-ai-python`.
