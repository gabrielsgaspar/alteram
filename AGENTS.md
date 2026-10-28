# AGENTS.md

Standing instructions for any coding agent working in this repository (Claude Code, Codex and others). Read this file in full before making changes. For the full background, see `ALTERAM_SETUP_BRIEF.md`.

## What this project is

Alteram is an AI adjudication system for small disputes. In v0, two lawyer agents (claimant and respondent) each read a written case and argue their side, and a judge agent reads both arguments and writes a verdict. Every claim must cite the numbered paragraphs of the case.

This is a learning project. Clear, small, well-tested code matters more than features. If a change makes the system harder to explain, it is probably the wrong change.

## Current scope: v0

In scope: case loading, the three agents, the LangGraph graph, the CLI, run logs, the order-swap check, tests and CI.

Out of scope until the owner says otherwise: retrieval, web search, tools for agents, rebuttal rounds, review panels, databases, cloud deployment, a web front end. If you think one of these is needed, say so and stop; do not build it.

## Commands

```bash
uv sync                                         # install dependencies
uv run alteram run cases/case-001.md            # run one case
uv run alteram run cases/case-001.md --follow   # same, printing events as they happen
uv run alteram swap cases/case-001.md           # order-swap check on the judge
uv run alteram rejudge runs/case-001/<file>.json  # current judge on saved arguments
uv run alteram eval --dry-run --n 3              # planned calls and cost, no model calls
uv run alteram eval --n 3                        # whole graph n times per case, vs expected
uv run alteram eval baseline eval/runs/<stamp>/summary.json  # keep as a baseline
uv run alteram eval compare <a.json> <b.json>    # differences, with intervals
uv run pytest                                   # tests (never call the real API)
uv run ruff check . && uv run ruff format .     # lint and format
```

Run `uv run ruff check .` and `uv run pytest` before saying a task is done.

## Layout

```
src/alteram/     package code: models, loader, graph, cli
prompts/         agent prompts as Markdown, one file per agent
cases/           test cases with numbered paragraphs
tests/           pytest tests
runs/            run logs as JSON, events beside them as .events.jsonl (gitignored)
eval/            eval runs (gitignored) and baselines (committed)
docs/            setup log, ideas, prompt change log
.claude/skills/  task-specific instructions for Claude Code
```

## Rules

### Secrets

- Never read, print, copy or edit `.env`. Read configuration only through environment variables in code.
- Never put a key, token or password in code, tests, logs, commits or chat.
- New variables go in `.env.example` with an empty value, and in the table below.

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API calls |
| `ALTERAM_LAWYER_MODEL` | Model ID for both lawyers |
| `ALTERAM_JUDGE_MODEL` | Model ID for the judge |
| `ALTERAM_RUN_BUDGET_USD` | Spending limit per run, swap or rejudge in USD (empty: 5) |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | Optional tracing |

### Agents and prompts

- Prompts live in `prompts/*.md`, never in Python strings. Code loads them by file name.
- Every prompt file starts with `version: N`. Follow `.claude/skills/prompt-change/SKILL.md` whenever a prompt changes.
- Do not edit prompts as a side effect of a code task. Prompt changes are their own task, approved by the owner.
- Lawyers' private thinking is logged in the run file and never passed to the judge.
- The judge must be able to answer `undecidable`.
- Model IDs come from environment variables, never hard-coded.

### Typed data

- Every agent input and output is a Pydantic model in `src/alteram/models.py`.
- Validate in code what code can check: citations must point to paragraphs that exist, and every point must cite at least one. Do not ask a model to check what code can check.
- Case metadata `kind` and `expected` are for evaluation only and must never reach an agent.

### Tests

- Tests never call a real model or the network. Use LangChain's fake chat models or fixtures.
- Each new function that holds logic gets a test. Bug fixes start with a failing test.
- Tests must pass in CI with no secrets set.

### Code style

- Python 3.12, type hints everywhere, ruff for lint and format.
- Small modules and functions. No clever abstractions until something is repeated three times.
- Prefer the standard library and the existing dependencies. Ask before adding a dependency, and say why.
- Check current official docs for LangGraph, LangChain and the Anthropic API before using a feature you are unsure of. They change often; do not rely on memory.

### Workflow

- For any change touching more than one file, show a short plan first and wait for approval.
- Keep commits small, with messages that say what changed and why.
- When a task is done, report: what changed, how it was tested, and anything you were unsure about.
- If the instructions here conflict with a request, point out the conflict instead of silently picking one.

## Definition of done for v0

- `uv run alteram run` works on all cases in `cases/`, and saves a complete run log.
- `uv run alteram swap` reports whether the verdict changes when argument order is swapped.
- `uv run pytest` and `uv run ruff check .` pass locally and in GitHub Actions without secrets.
- `README.md` explains setup and use in under five minutes of reading.
