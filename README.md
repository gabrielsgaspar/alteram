# Alteram

Alteram is an AI adjudication system for small consumer disputes. It is a learning project: two AI lawyers argue a written case and an AI judge decides it, citing the case's numbered paragraphs.

> **Not legal advice.** Alteram's outputs are experiments. They are not legal advice and not binding on anyone.

## What v0 does

- **Reads a case** from `cases/`: a Markdown file with numbered paragraphs.
- **Two lawyer agents** (claimant and respondent) each argue their side. Every point must cite paragraphs that exist, and code checks this.
- **A judge agent** reads both arguments and returns `claimant`, `respondent` or `undecidable`, with a confidence score and the facts that would change its decision. It never sees the lawyers' private thinking.
- **Saves a run log** for every run: both arguments, the verdict, prompt versions and hashes, models, tokens and cost.
- **Checks the judge for order bias** (`swap`), re-judges saved arguments (`rejudge`), and scores the whole system against each case's expected outcome (`eval`).

Prompts are in `prompts/*.md`; models are set by environment variables.

## Setup (WSL2)

You need `git` and [uv](https://docs.astral.sh/uv/) installed, and an Anthropic API key.

```bash
git clone https://github.com/gabrielsgaspar/alteram.git && cd alteram
uv sync
cp .env.example .env
nano .env
uv run pytest
```

In `.env`, fill in:

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API calls |
| `ALTERAM_LAWYER_MODEL` | Model ID for both lawyers, e.g. `claude-sonnet-5-5` |
| `ALTERAM_JUDGE_MODEL` | Model ID for the judge, e.g. `claude-opus-5-5` |
| `ALTERAM_RUN_BUDGET_USD` | Spending limit per run, swap or rejudge (empty: 5) |
| `LANGSMITH_*` | Optional tracing; leave empty to turn it off |

Tests never call a model, so `uv run pytest` passes before you add a key.

## Use

### Run a case

```bash
uv run alteram run cases/case-001.md
uv run alteram run cases/case-001.md --follow
uv run alteram run cases/case-001.md --order respondent_first
```

`--follow` prints events as they happen. `--order` sets which argument the judge reads first. The run log goes to `runs/case-001/<timestamp>.json`, with events beside it as `.events.jsonl`.

### Order-swap check

```bash
uv run alteram swap cases/case-001.md --repeats 5
```

This runs the lawyers once, then the judge `--repeats` times in each order on the same two arguments, and reports whether the winner changes with the order.

### Re-judge saved arguments

```bash
uv run alteram rejudge runs/case-001/<file>.json --repeats 3
```

Runs the current judge prompt on the arguments from an earlier run or swap file, without calling the lawyers again. Use it to compare judge prompt versions on identical input. It refuses if the case file has changed since, unless you pass `--allow-changed-case`.

### Evaluate

```bash
uv run alteram eval --dry-run --n 3
uv run alteram eval --n 3
uv run alteram eval baseline eval/runs/<stamp>/summary.json
uv run alteram eval compare <a.json> <b.json>
```

- `--dry-run` prints the planned calls and an estimated cost, and makes no calls.
- `eval --n 3` runs the whole graph 3 times per case and scores the verdicts against each case's `expected` outcome, with bootstrap intervals. Results go to `eval/runs/<stamp>/`.
- `--cases` points at another case folder; `--seed` fixes the bootstrap.
- `baseline` copies a summary into `eval/baselines/`, which is committed.
- `compare` shows the differences between two summaries (b − a), with intervals.

**Current baseline** (`eval/baselines/20261029T185846Z.json`, judge prompt v2): 83% accuracy [50%, 100%] over 4 cases × 3 runs, $0.12 per run. With only 4 cases the interval is wide, so treat it as a smoke test, not a measurement.

### Build → review harness

For coding work on Alteram itself, not for disputes:

```bash
uv run python scripts/build_review.py tasks/<task>.md --loops 3
```

A builder agent (`claude -p`) implements the task file, the script runs ruff and pytest, and a fresh read-only reviewer agent checks the result against the task's acceptance criteria. The two agents repeat until the reviewer approves or `--loops` runs out. `--budget` and `--call-budget` cap the spend.

The harness refuses to start on `main` or with uncommitted changes. It commits each loop on your branch, and never pushes or merges. Logs go to `.loop/<timestamp>/`. Start new tasks from `tasks/TEMPLATE.md`. It needs the Claude Code CLI with its sandbox (Linux or WSL2). See [docs/harness-plan.md](docs/harness-plan.md).

### Lint and format

```bash
uv run ruff check .
uv run ruff format .
```

## Layout

```
src/alteram/       package: models, loader, graph, validation, CLI, swap, rejudge, eval, pricing
prompts/           agent prompts as Markdown, one per agent, each starting with `version: N`
cases/             test cases with numbered paragraphs
tests/             pytest tests (no real model calls)
runs/              run logs and events (gitignored)
eval/              eval runs (gitignored) and baselines (committed)
docs/              setup log, v1 design, ideas, prompt change log, harness plan
scripts/           build_review.py, the build → review loop
harness/           builder and reviewer prompts and the review schema
tasks/             task files for the harness
.claude/skills/    task instructions for Claude Code (new-case, prompt-change)
```

## Further reading

- [ALTERAM_SETUP_BRIEF.md](ALTERAM_SETUP_BRIEF.md): the full v0 brief, covering goals, design and build steps.
- [docs/ALTERAM_V1_DESIGN.md](docs/ALTERAM_V1_DESIGN.md): the design for the next iteration.
- [docs/SETUP_LOG.md](docs/SETUP_LOG.md): what happened at each build step, with decisions and review notes.
- [docs/prompt-log.md](docs/prompt-log.md): every prompt change and its results.
- [AGENTS.md](AGENTS.md): rules for coding agents working in this repository.
