# Alteram: Claude Code session prompts (M0, harness, M1)

_Written 27 October 2026, from `ALTERAM_V1_DESIGN.md` and the repo state at commit 5c2c1f7. Each prompt is one Claude Code session. Start every session with `/clear` or a fresh `claude`. Every prompt ends with "Done when" checks; the agent must run them and report the results, not just claim them. The same section works as acceptance criteria for the build→review harness once it exists._

Launch syntax: `claude --model <alias> --effort <level>`. Aliases and levels checked against the Claude Code docs: `opus` = Opus 5.5, `sonnet` = Sonnet 5.5, `opusplan` = Opus in plan mode then Sonnet for execution; effort `low|medium|high|xhigh|max` (default `medium`).

## Order

| # | Session | Model / effort | Needs first |
| --- | --- | --- | --- |
| 1 | Reason-coverage fix (M0) | `sonnet` / `medium` | — |
| 2 | GitHub Actions CI (M0, step 10) | `sonnet` / `medium` | 1 |
| — | You: rotate keys | — | — |
| 2a | Install WSL2 and Docker Desktop (on Windows) | `sonnet` / `medium` | 2 pushed |
| 2b | Set up the WSL2 workspace (inside Ubuntu) | `sonnet` / `medium` | 2a |
| 3 | Sandbox for `.env` in WSL2 | `sonnet` / `high` | 2b |
| 4 | Build→review harness | `opus` / `high` | 3 |
| 5 | `alteram rejudge` (M1) | `sonnet` / `high` | 2 |
| 6 | Pricing table and budget stop (M1) | `sonnet` / `medium` | 2 |
| 7 | `alteram eval` (M1) | `opus` / `high` (or `opusplan`) | 5, 6 |
| 8 | Event stream from the v0 graph (start of M2) | `sonnet` / `high` | 7; also the M2/M3 order decision |

## 1. Reason-coverage fix

```text
Read AGENTS.md and the judge v1 → v2 entry in docs/prompt-log.md. Show me a plan before editing.

Task: in src/alteram/validate.py, change check_reason_coverage so that reasons whose label is in PART_LABELS (C-outcome, C-against, R-outcome, R-against) are allowed as optional extras: not required, not counted as unknown. A duplicate of any label is still an error. Every numbered point label (C1…, R1…) is still required exactly once. Don't touch prompts, cases or the judge prompt version. Don't run anything that calls the Anthropic API.

Done when, and report each with evidence:
1. New tests in tests/test_validate.py pass: (a) all numbered labels plus C-against and R-against → passes; (b) the exact failure logged in our runs, "verdict reasons: missing [], unknown ['C-against', 'R-against']", now passes on the same inputs; (c) a duplicated R-against → CoverageError naming it; (d) a missing numbered label → CoverageError naming it; (e) an unknown label such as C9 or "C (requested outcome)" → CoverageError.
2. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` all pass; report the test count.
3. `git diff --stat` shows only validate.py and test_validate.py changed.
Then append one line to docs/prompt-log.md under the v2 entry: "Code fix: part labels allowed as optional reasons (commit <hash>)". Commit with a message saying what and why. Don't push.
```

Afterwards you run the paid check: `uv run alteram swap cases/case-002.md --repeats 2`. Every judge call should show `attempts: 1`. Then push.

## 2. GitHub Actions CI

```text
Read AGENTS.md. Step 10 of ALTERAM_SETUP_BRIEF.md. Show me a plan first.

Task: add .github/workflows/ci.yml that runs on push and pull_request, on ubuntu-latest: check out the repo; install uv with the official astral-sh/setup-uv action (check its current docs for the current major version and pin it); use the Python version in .python-version; `uv sync --locked`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run pytest`. No secrets. Set LANGSMITH_TRACING=false for the job. Cache uv if the action supports it.

Before pushing, prove the suite can't need secrets or network: list every load_dotenv and os.environ read in src/ and tests/, and confirm tests never load .env and never construct a real chat model client that calls out.

Done when, and report each with evidence:
1. The same four commands pass locally.
2. On a branch named ci/setup: commit, push, and run `gh run watch` until the workflow finishes. If it fails, read `gh run view --log-failed`, fix, and push again, at most 3 attempts; then stop and report.
3. Report the green run's URL and its duration. Open a PR to main with `gh pr create`, and don't merge it.
```

## You, before 2a: rotate keys

The Anthropic and LangSmith keys left your machine in the 27 October zip. Revoke both in their consoles and create new ones. Don't put them in the old `.env`; you'll create a fresh one in 2b.

## 2a. Install WSL2 and Docker Desktop (Claude Code on Windows)

Run in your current Windows repo folder: `claude --model sonnet --effort medium`. The agent can't elevate itself, reboot, or click through installers. It checks, tells you exactly what to run in an **administrator** PowerShell, and verifies afterwards. After the reboot, reopen the session with `claude --continue` in the same folder.

```text
You are guiding me through installing WSL2 (Ubuntu) and Docker Desktop on this Windows machine, so Alteram development can move into WSL2. Read AGENTS.md first.

Rules for this session:
- Never run anything elevated and never change system settings yourself. For each step that needs admin rights, a reboot or a GUI, tell me the exact command or click path, say why, and wait for me to report back.
- Don't modify any file outside this repository. Inside it, change only docs/SETUP_LOG.md.
- Never read, print or copy .env.
- Check current official docs before giving commands (Microsoft's "Install WSL" page; Docker's "Install Docker Desktop on Windows" and "WSL 2 backend" pages), and show me the links.

Step 0, repo safety (do this first): run `git status`, `git log origin/main..HEAD --oneline` and `git status --ignored --short`. Everything tracked must be committed and pushed; if not, list it and stop until I've committed and pushed. List the ignored items worth keeping that git won't carry over (I expect `runs/` and `.env`) and tell me how they'll be handled in 2b.

Step 1, prerequisites (read-only checks you can run): the Windows edition and build (Docker Desktop's current requirements), whether hardware virtualisation is on, whether WSL is already installed (`wsl --status`, `wsl -l -v`, `wsl --version`), and free disk space on C:. Report pass/fail against the documented requirements and stop if any fails.

Step 2, WSL2: give me the admin-PowerShell command to install WSL with Ubuntu (per the current Microsoft docs, including the fallback if WSL is partly installed), then the reboot, then first launch of Ubuntu and creating a Linux username and password. After I say it's done, verify `wsl -l -v` shows Ubuntu at VERSION 2, `wsl --version` meets Docker's minimum, and Ubuntu is the default distro.

Step 3, Docker Desktop: confirm the package ID with `winget show Docker.DockerDesktop` (or give the official installer link if that fails), and prefer the per-user install, which needs no admin rights, if the docs still offer it. Then guide me through first launch: accept the terms (tell me the licence threshold so I can confirm personal use is free), confirm the WSL 2 engine is on, and enable WSL integration for Ubuntu under Settings > Resources > WSL Integration.

Done when, and report each with evidence:
1. `wsl -l -v` shows Ubuntu, VERSION 2, as the default.
2. `docker version` in PowerShell shows both Client and Server.
3. `wsl -d Ubuntu -- docker run --rm hello-world` prints Docker's hello message.
4. `wsl -d Ubuntu -- uname -r` shows a WSL2 kernel.
5. You've appended one line to docs/SETUP_LOG.md Decisions: "2026-MM-DD: WSL2 (Ubuntu, version) and Docker Desktop (version) installed; development moves to WSL2", committed it, and I've pushed.
If anything fails, stop and show me the exact error and the doc section that covers it.
```

## 2b. Set up the WSL2 workspace (Claude Code inside Ubuntu)

First, by hand in the Ubuntu terminal (one bootstrap step the agent can't do for itself):

```bash
curl -fsSL https://claude.ai/install.sh | bash
# open a new Ubuntu terminal, then:
claude --version
mkdir -p ~/projects && cd ~/projects
claude --model sonnet --effort medium   # log in when the browser opens
```

Then paste:

```text
You are helping me set up an Alteram development workspace inside WSL2 Ubuntu. The repo is github.com/gabrielsgaspar/alteram; it will live at ~/projects/alteram. The old Windows copy is at /mnt/c/Users/Gabriel Gaspar/Projects/alteram and must not be modified.

Rules for this session:
- You can't type my sudo password. For every command that needs sudo, print it for me to run in my own terminal, say what it installs and why, and wait. Run non-sudo commands yourself.
- Check current official install docs for each tool (GitHub CLI's Linux apt instructions, uv, Node.js LTS, Herdr's Linux installer, and Claude Code's sandboxing page for its Linux dependencies) and show the links before giving commands.
- Never read, print or copy any .env file, including the Windows one.
- Change nothing outside ~/projects/alteram except installing these tools and the git/gh configuration below.

Steps:
1. System packages (I run them): git, curl, ca-certificates, build-essential, and the sandbox's Linux dependencies (I expect bubblewrap and socat; confirm from the docs).
2. GitHub CLI from GitHub's official apt repository; then I run `gh auth login`. Set git user.name and user.email (ask me for the values) and `init.defaultBranch main`.
3. uv with the official installer. Node.js current LTS by the method the Node.js site recommends for Ubuntu, for the Next.js work later. Herdr's Linux build.
4. Clone the repo to ~/projects/alteram with gh. Copy the gitignored `runs/` folder from the Windows copy into the new clone (cp -r, preserving timestamps), because past results are referenced in docs/prompt-log.md. Do not copy .env.
5. I create ~/projects/alteram/.env myself from .env.example in an editor, with the new rotated keys. Wait for me.
6. Run `uv sync`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`.

Done when, and report each with evidence:
1. `git --version`, `gh --version` (and `gh auth status` logged in), `uv --version`, `node --version` (current LTS), `herdr --version`, `claude --version` all work, and `which bwrap socat` finds both.
2. `git -C ~/projects/alteram status` is clean on main and up to date with origin; `git config core.autocrlf` is unset or false.
3. `ls ~/projects/alteram/runs` shows case-001 to case-004, with the same file count as the Windows copy.
4. `git check-ignore -v .env` matches, and .env exists (check existence only, with `test -f`; don't read it).
5. The four uv commands pass; report the test count, which must equal the Windows count.
6. `docker run --rm hello-world` works from this Ubuntu shell.
7. Append a line to docs/SETUP_LOG.md Decisions: "2026-MM-DD: workspace moved to WSL2 at ~/projects/alteram; Windows copy retired." Commit, and tell me to push.
If anything fails, stop and show the error.
```

After 2b, rename the Windows folder (for example to `alteram-windows-old`) so you can't edit the wrong copy by mistake. If you want Cowork to keep reading the repo directly, connect the WSL folder in the Claude desktop app (`\\wsl.localhost\Ubuntu\home\<you>\projects\alteram`). Otherwise Cowork will work from GitHub and the project docs.

## 3. Sandbox for `.env` (in WSL2)

```text
Read AGENTS.md and .claude/settings.json. We've moved the repo into WSL2 Ubuntu so the Claude Code sandbox works. Check the current Claude Code sandboxing and permissions docs, then show me a plan before editing.

Task: propose and apply a .claude/settings.json change that enables the Bash sandbox and denies reads of .env files at OS level (repo .env and **/.env patterns), keeping the existing Read deny rules. Keep `uv sync`, `uv run pytest`, git and gh working; if the sandbox's network rules would block them, propose the narrowest allowance and explain it.

Never read, print or test against the real .env. Test with a canary instead: create .env.canary containing only CANARY=not-a-secret, add it to the deny patterns for the test, and delete both afterwards.

Done when, and report each with evidence:
1. With the sandbox on, all of these fail to read .env.canary: `cat`, `head`, `grep -r CANARY .`, `python -c "print(open('.env.canary').read())"`, and `uv run python -c` doing the same.
2. `uv sync`, `uv run ruff check .` and `uv run pytest` still pass inside the sandbox.
3. The canary file and canary pattern are removed; `git status` shows only settings.json changed.
4. Add one line to docs/SETUP_LOG.md Decisions: sandbox enabled, date, what was verified. Commit; don't push.
If any canary read succeeds, stop immediately and report which command.
```

## 4. Build→review harness

```text
Read AGENTS.md and docs/harness-plan.md. Phase 1: check the current Claude Code CLI docs and confirm, with links, every flag the plan uses (-p, --output-format json/stream-json, --json-schema and structured_output, --resume with session_id, --permission-mode acceptEdits, --allowedTools/--disallowedTools rule syntax, --max-budget-usd, --permission-prompts none, --append-system-prompt-file, total_cost_usd), and that .claude/settings.json deny rules and the sandbox apply in -p mode. Report findings and a file plan, then stop until I approve.

Phase 2: build what the plan lists: scripts/build_review.py (standard library only), harness/builder.md, harness/reviewer.md, harness/review_schema.json, tasks/TEMPLATE.md, `.loop/` in .gitignore. The script must take the claude binary from ALTERAM_CLAUDE_BIN (default `claude`) so tests can substitute a fake.

Done when, and report each with evidence:
1. Tests in tests/test_build_review.py use a fake claude script (no real calls) and cover: refuses to run on main or with a dirty tree; stops on "approve"; stops after --loops N with "changes"; a failing ruff/pytest gate skips the reviewer and feeds the failure to the builder; a reply with no structured_output is treated as "changes" with an error, not as approval; the total budget stop; the builder's session is resumed and the reviewer's is fresh each loop; the reviewer's allowed tools exclude Edit and Write.
2. `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` pass.
3. One real smoke run, which I approve before it starts: a task file tasks/smoke.md asking for a one-line module docstring in src/alteram/__init__.py, `--loops 2`, total budget $1. Report: branch name, commits made, the final verdict, total cost, and the paths of the two logs.
Commit on a branch; don't push or merge.
```

## 5. `alteram rejudge`

```text
Read AGENTS.md, src/alteram/graph.py, swap.py and cli.py, and the "Paired re-judging" entry in docs/IDEAS.md. Show me a plan first.

Task: add `uv run alteram rejudge <run-or-swap-file> [--repeats 5]`. It loads the claimant and respondent arguments saved in an earlier run or swap file and runs the *current* judge prompt on exactly those arguments, `--repeats` times in each order, using run_judge. It must never call the lawyers. Refuse to run if the case file's current sha256 differs from the one saved in the source file, unless --allow-changed-case is given. Save runs/<case-id>/<timestamp>-rejudge.json with: the source file path and its sha256, the source and current judge prompt versions and hashes, every judge result, and a paired summary comparing source verdicts with new verdicts (winners per order, mean confidence, within/across-order disagreement, retry rate). Print that summary.

Done when, and report each with evidence:
1. Tests with fakes: the lawyer models are never called; the arguments passed to the judge are byte-identical to the saved ones; a case-hash mismatch is refused, with a clear message; it works from a plain run file and from a swap file; the summary is correct on a hand-made example.
2. ruff check, ruff format --check and pytest pass.
3. A dry run against runs/case-002/20261026T220457Z-swap.json with a fake judge works end to end and writes a valid file.
No real API calls. Commit; don't push.
```

## 6. Pricing table and budget stop

```text
Read AGENTS.md and ALTERAM_V1_DESIGN.md section 9.3. Show me a plan first.

Task: add src/alteram/pricing.py with a dated price table (input and output $ per million tokens) for the models we use. Check the current Anthropic pricing page and record its URL and the date checked in the file. Add cost_usd to AgentCall, computed from the reported model and token counts. Add a per-run budget read from ALTERAM_RUN_BUDGET_USD (default 5; add it to .env.example and the AGENTS.md table), checked before every model call. Going over it is a hard failure, saved in the -failed.json like other failures. The run and swap CLI output shows cost per agent and in total. Unknown model → error, not $0.

Done when, and report each with evidence:
1. Unit tests: cost on a hand-computed example; an unknown model raises; the budget stop triggers before the call that would exceed it, with fakes; a failed run records the cost spent so far.
2. Recompute the cost of runs/case-001/20261026T205844Z.json with the new function and report it. It should be about $0.10; explain any difference.
3. ruff check, ruff format --check and pytest pass.
No real API calls. Commit; don't push.
```

## 7. `alteram eval`

```text
Read AGENTS.md, ALTERAM_V1_DESIGN.md sections 11.1, 11.2 (whole-pipeline and judge rows) and 11.4, and the current CLI. Plan mode: show me the design first, including file formats.

Task: add `uv run alteram eval [--cases cases/] [--n 3] [--dry-run]`. It runs the full graph n times per case, alternating judge order, and writes eval/runs/<timestamp>/ with every run file plus summary.json and summary.md. Per case: winner distribution, agreement with `expected`, confidence mean and spread, cost, latency per node, retry rate per agent, failures and budget stops. Overall: accuracy against `expected` with a seeded bootstrap 95% interval over cases, total cost, and a printed warning when there are fewer than 10 cases. `--dry-run` prints the planned number of calls and a cost estimate from pricing.py and past runs, and makes zero model calls. Add `alteram eval baseline <summary.json>` (copies it to eval/baselines/, to be committed) and `alteram eval compare <a> <b>` (differences per metric, with intervals where defined). eval/runs/ is gitignored; eval/baselines/ is not.

Done when, and report each with evidence:
1. Tests with fakes: n × cases runs happen with alternating orders; the summary is correct on a hand-made set of run files; the bootstrap is reproducible with the seed and gives [1, 1] when every case is correct; dry run never calls the model factory; one run's failure is recorded and the eval continues; compare shows the right differences on two hand-made summaries.
2. ruff check, ruff format --check and pytest pass.
3. `uv run alteram eval --dry-run --n 3` on the real cases prints a plan and an estimate; report it.
No real API calls; I'll run the real baseline. Commit; don't push.
```

Afterwards you run `uv run alteram eval --n 3` (estimate: about $1.50 for 4 cases), then `alteram eval baseline`, and commit the baseline. That closes M1.

## 8. Event stream from the v0 graph (optional; start of M2)

```text
Read AGENTS.md and ALTERAM_V1_DESIGN.md sections 3 (principle 8) and 10.3. Show me a plan first. No database, no web code in this session.

Task: add src/alteram/events.py with a typed Event model (case_id, seq, ts, stage, agent, side, type, payload) and the event types in 10.3 that v0 can produce: agent_call_started, agent_call_finished (tokens, cost), check_failed, retry, state_change, error. Emit them from every node through LangGraph's custom stream writer (check the current LangGraph docs for the API). The run, swap and eval commands save events.jsonl next to each run file. `alteram run --follow` prints events as they happen.

Done when, and report each with evidence:
1. Tests with fakes: the event order for a full run is correct; seq is strictly increasing per run; a retry produces check_failed then retry; the judge's agent_call_started payload contains no lawyer thinking (reuse the marker test); events.jsonl parses back into Event objects.
2. ruff check, ruff format --check and pytest pass.
No real API calls. Commit; don't push.
```

## What these sessions don't cover

- **Mine (docs):** README (step 11, once CI is green); updating AGENTS.md scope for v1 (needed before any database, retrieval or web work, since today's AGENTS.md tells Claude Code to stop on those); docs/PRIVACY.md; turning M2–M5 into session prompts once the decisions below are made.
- **Yours:** the retrospective (step 12, three questions); key rotation; the manual parts of 2a and 2b (admin commands, reboot, Docker's first launch, sudo commands, `gh auth login`, creating `.env`); the paid confirmation swap and eval baseline; raising the Console spend limit before M3; writing five human cases (two respondent wins); later, the retrieval gold set (~60 questions), the citation set (~200 triples) and the FOS selection (150 decisions).
- **Decisions blocking later milestones:** v1 scope (I suggest M0–M5 as v1); M2 before or after M3; the 10 open questions in section 15 of the design (Jev for M4, per-case budget for M1, judge questions to parties for M6–M7, and so on).
- **Admin:** apply for the Find Case Law computational-analysis licence; confirm FCA and FOS reuse terms; Voyage and TypeSafe accounts and keys (`.env` names to be set when M3/M4 start).
- **Multi-session milestones, rough session counts:** M2 rest (Compose + Postgres + Alembic; FastAPI + SSE + worker; Next.js case room; timeline): 4–5. M3 law library (schema and store; one ingester per source; contextual headers and embeddings; inspector): 4–6. M4 retrieval and checker (retrieve; L0–L2 + L4; L3 with Jev and Claude; calibration and eval): 4–5. M5 lawyers with research: 2–3. M6–M10: 3–5 each. M11: 3–4.
