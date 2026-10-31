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

## Ship

`scripts/ship.py` takes a task all the way to a merged PR: it runs the build → review loop in a worktree, checks a merge gate in code, pushes, opens or updates the PR, waits for CI and merges. `build_review.py` itself still never pushes or merges; `ship.py` does, and only after the gate passes.

### Usage

```bash
# New work: the task file must already be on origin/main.
uv run python scripts/ship.py task tasks/<name>.md [--loops 3] [--budget 5] [--no-merge]

# An existing branch: reviewer first, builder only if the reviewer asks for changes.
uv run python scripts/ship.py branch <branch> --task tasks/<name>.md [--loops 3] [--budget 5] [--no-merge]

# The same, in a Herdr workspace (or straight in this terminal if Herdr is not running).
bash scripts/ship-herdr.sh task tasks/<name>.md
bash scripts/ship-herdr.sh --print task tasks/<name>.md   # only print the herdr commands
```

- **task mode** creates branch `task/<name>` and worktree `~/projects/alteram-wt/<name>` from `origin/main`, then runs `build_review.py` there.
- **branch mode** uses the worktree that already has the branch checked out, or creates `~/projects/alteram-wt/<branch, sanitised>`. It first merges `origin/main` into the branch; on a conflict it aborts the merge and stops (exit 3). Then it runs `build_review.py --review-first`.
- `--loops` and `--budget` cover the whole run, including loops spent fixing CI.
- The reviewer always sees `git diff origin/main...HEAD`, the whole branch.
- `ship.py` never switches the branch of the worktree it is launched from. It removes a worktree only if it created it, after copying `.loop/` to `~/projects/.ship/<name>-<stamp>-logs/`.
- `~/projects/.ship/<name>` is a symlink to the worktree's `.loop/latest`, so log viewers can tail a fixed path. Each run writes `~/projects/.ship/<name>-<UTC stamp>.json`: mode, branch, PR URL, loops, cost, verdict, gate results, CI result, merge SHA and exit code.
- `gh` and `claude` come from `ALTERAM_GH_BIN` and `ALTERAM_CLAUDE_BIN` (defaults `gh` and `claude`); the tests substitute fakes.

### Guard

`ship.py` refuses (exit 2) if the current directory or a target worktree is under `/mnt`, is not under `~/projects/`, or is not on ext4 (`stat -f -c %T` must say `ext2/ext3`).

### Merge gate

Checked in code after every reviewer approval. All four must pass, or `ship.py` stops before pushing, says why, and exits 3:

1. The final reviewer verdict is `approve` with a non-empty `checked` list.
2. Every file in `git diff origin/main...HEAD --name-only` matches a backticked path or glob in the task file's `## In scope` section. A pattern ending in `/` is a directory.
3. No changed file is under `.env*`, `.claude/`, `.github/`, `prompts/`, `cases/`, `pyproject.toml` or `uv.lock`, unless the In-scope list names it explicitly: an exact path or directory, not a glob.
4. A secret scan of the added lines finds no Anthropic, LangSmith or GitHub token prefix, no PEM block header, and no `KEY=` or `TOKEN=` assignment with a value of 16 or more characters. It reports the file and the kind of match, never the match itself.

### CI and merge

After the gate, `ship.py` runs `git push -u origin HEAD` and creates the PR with the task file's title and a body holding the task file, the reviewer's `checked` list, the loops used and the cost. If a PR already exists, the same goes in a comment instead. It then waits for `gh pr checks --watch --fail-fast`:

- No checks within 3 minutes: exit 3.
- CI fails and loops remain: the failed log (`gh run view --log-failed`, last 4000 characters) goes to the builder as must-fix, then the gate and reviewer run again and the branch is pushed again. No loops left: exit 3.
- CI passes: unless `--no-merge`, `gh pr merge --merge --delete-branch` (with `--repo`, so gh does not touch local branches or try to check out `main` inside the worktree). Then, if the launching worktree is on `main` with a clean tree, `git pull --ff-only` there.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Merged, or approved and green with `--no-merge` |
| 2 | Refused: guard, task file not on `origin/main`, branch or worktree already exists |
| 3 | Needs you: no approval, merge gate failed, merge conflict, CI failed or never started |
| 4 | Budget reached |

### Herdr layout

`scripts/ship-herdr.sh` takes the same arguments and creates a Herdr workspace labelled `ship <name>`:

```
┌──────────────────────┬──────────────────────────────────────────────┐
│                      │ tail -F ~/projects/.ship/<name>/builder.log  │
│  ship.py <args>      ├──────────────────────────────────────────────┤
│                      │ tail -F ~/projects/.ship/<name>/reviewer.log │
└──────────────────────┴──────────────────────────────────────────────┘
```

If `herdr` is not installed or no server is running, it says so and runs `ship.py` in the current terminal.

### Trigger from Windows

From PowerShell:

```powershell
wsl.exe -- bash -lic 'cd ~/projects/alteram && git pull --ff-only && bash scripts/ship-herdr.sh task tasks/<name>.md'
```

## GitHub flow: issue → label → plan comment

A second, GitHub-side entry point. It only plans; it never builds.

1. Someone opens an issue from the **Agent task** template (`.github/ISSUE_TEMPLATE/agent-task.md`). It has the same sections as `tasks/TEMPLATE.md`: Goal, In scope, Out of scope, Done when.
2. A person with admin or write access adds the `agent-plan` label. Run `bash scripts/create_labels.sh` once to create `agent-plan`, `agent-build` and `needs-human`; it is safe to run again.
3. `.github/workflows/agent-plan.yml` runs on `issues: labeled` and nothing else. A guard step checks the labelling user's repo permission first and stops if it is not admin or write.
4. Claude (Opus, read-only: `Read`, `Grep`, `Glob`, and `git log` / `git diff`) reads `AGENTS.md`, the design docs and the issue, and returns a structured result. A later step posts it as **one comment** on the issue: a plan (files, steps, risks, a "Done when" checklist that needs no paid API calls), or a plain statement that the issue is unclear or out of scope under `AGENTS.md`.

The issue text is treated as data, not instructions. The agent cannot post, edit files, or change labels or settings; a plain workflow step posts the comment with the job token (`contents: read`, `issues: write`). Because that token is `GITHUB_TOKEN`, the comment does not trigger any other workflow. The workflow only runs once it is on `main`.

How it relates to the local ship tool: the issue comment is advice for a person. Turning an approved plan into work is still local. Copy it into `tasks/<name>.md` and run `scripts/ship.py` (or `ship-herdr.sh`) as described in [Ship](#ship). The `agent-build` and `needs-human` labels exist for that later step; nothing in GitHub reads them yet.
