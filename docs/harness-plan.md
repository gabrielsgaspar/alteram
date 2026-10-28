# Build → review harness: plan

_Proposed 27 October 2026. Not built yet. It is item 4 in the brief's post-v0 list, brought forward as tooling for all later coding work._

## Goal

Hand a coding task to an automatic loop: a **builder** agent implements it, code runs the tests, a **reviewer** agent checks the result against the task, and the builder fixes what the reviewer found. This repeats up to N times, or until the reviewer approves. Gabriel watches it in three panes and stays the only one who merges.

## Layout (Herdr, one tab, three panes)

```
┌──────────────────────┬──────────────────────┐
│                      │  2. Builder          │
│  1. Your shell       │  (live builder log)  │
│  (run the loop,      ├──────────────────────┤
│   git, tests)        │  3. Reviewer         │
│                      │  (live reviewer log) │
└──────────────────────┴──────────────────────┘
```

Herdr (herdr.dev, v0.9.x, native Windows supported) gives the panes and shows each agent's state. **The loop itself does not depend on Herdr.** Panes 2 and 3 only display log files the loop writes, so the loop works the same in a plain terminal or in CI.

## Why a script with `claude -p`, not Herdr driving interactive agents

Herdr can send prompts into interactive Claude Code panes and wait for them (`herdr pane run`, `herdr agent wait --until done`). But:

- **State detection is heuristic.** Its docs flag a race where `agent wait` can see a stale "done" before the new prompt starts.
- **An interactive pane can stop on a permission prompt** with nobody there to answer it.
- **Reading results means scraping terminal output.**
- **Herdr's API is pre-1.0 and may change.**

`claude -p` (headless Claude Code) instead gives exit codes, JSON output, a schema-checked verdict (`--json-schema`), a cost figure (`total_cost_usd`) and a spend cap (`--max-budget-usd`). That is deterministic enough to loop on. Herdr's community loop plugins (e.g. herdr-review-loop, herdr-peer-review) exist but are unverified.

## The loop

Run from pane 1: `uv run python scripts/build_review.py tasks/<task>.md --loops 3`

0. **Pre-checks.** Refuse to start on `main` or with uncommitted changes. Create `.loop/<timestamp>/` (gitignored).
1. **Builder.** Runs `claude -p` with the task file, the `AGENTS.md` rules (loaded through `CLAUDE.md` as usual) and, from loop 2 on, the reviewer's must-fix list plus any test failures.
   - Settings: `--permission-mode acceptEdits`, `--allowedTools` limited to the repo's commands (`Bash(uv run *)`, `Bash(git diff *)`, `Bash(git status *)`), `--max-budget-usd`, `--output-format stream-json --verbose`.
   - The same builder session is resumed across loops (`--resume <session_id>`), so it remembers what it did.
2. **Gate, in code rather than by a model.** The script runs `uv run ruff check .` and `uv run pytest` itself. If either fails, the output goes back to the builder and counts as a loop, and the reviewer isn't called.
3. **Reviewer.** A **fresh** `claude -p` session each loop, so it judges independently.
   - Read-only: Read, Grep, Glob, `Bash(git diff *)` and `Bash(uv run pytest *)`; no Edit or Write.
   - It gets the task file and `git diff main...HEAD` plus uncommitted changes.
   - It returns a schema-checked verdict: `{"verdict": "approve" | "changes", "must_fix": [...], "nice_to_have": [...], "checked": [...]}`.
4. **Stop on approval, or after N loops.**
   - The script prints a summary: loops used, cost, final verdict, and where the logs are.
   - It commits each loop on the branch with a message naming the loop, so every round's diff is reviewable. It never pushes and never merges.
5. **Logs.** Each agent's stream is written as readable text to `.loop/<timestamp>/builder.log` and `reviewer.log`, with the raw JSON alongside. Panes 2 and 3 run `Get-Content -Wait .loop\latest\builder.log` and `...\reviewer.log`.

## Guardrails

- **Cost:** a per-call `--max-budget-usd` and a total budget for the run. Stop when it's reached.
- **Safety:** never `main`; never push; never read `.env`. The existing `.claude/settings.json` deny rules still apply in `-p` mode. Don't use `--bare`, which skips `CLAUDE.md`/`AGENTS.md` and needs an API key instead of the Claude Code login.
- **Scope:** a task file must say what is in and out of scope and how to check the work is done (acceptance criteria). The reviewer judges against that file, not against taste.
- **Honesty:** the reviewer must say which acceptance criteria it actually checked. "Looks good" without checks is not an approval.

## Files to create

- `scripts/build_review.py`: the loop (standard library only, works on native Windows).
- `harness/builder.md`, `harness/reviewer.md`: role prompts, kept apart from Alteram's own `prompts/`.
- `harness/review_schema.json`: the verdict schema.
- `tasks/TEMPLATE.md`: goal, in scope, out of scope, acceptance criteria.
- `.gitignore`: add `.loop/`.
- Tests for the script's pure logic (argument parsing, the stop rule, reading the verdict) using a fake `claude` command; no real calls in tests.

## Claude Code prompt (phase 1 = research and plan only)

> Read AGENTS.md and docs/harness-plan.md. We're building the build→review harness it describes. **Phase 1 only:** check the current Claude Code CLI docs and confirm, with links, the flags the plan relies on: `-p`, `--output-format stream-json`/`json`, `--json-schema` and `structured_output`, `--resume` with `session_id`, `--permission-mode acceptEdits`, `--allowedTools` and `--disallowedTools` rule syntax, `--max-budget-usd`, `--permission-prompts none`, `--append-system-prompt-file`, `total_cost_usd`. Also confirm that `.claude/settings.json` deny rules apply in `-p` mode. Then show me a plan for the files listed in the doc. Don't write files until I approve. No new dependencies.

## First tasks to run through it

1. The judge reason-coverage fix: small, testable, and already specified in `docs/prompt-log.md`.
2. Step 10, GitHub Actions CI.
3. `alteram rejudge` (see `docs/IDEAS.md`).

## Open questions

- Should the builder see the reviewer's full output or only `must_fix`? Start with `must_fix` only, to avoid scope creep.
- One reviewer, or two from different model families (the brief's "reviewers → aggregator")? Start with one; add Codex later as a second reviewer.
