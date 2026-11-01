# Alteram v0: setup log

One checkbox per step in `ALTERAM_SETUP_BRIEF.md` section 8. Tick a step only when its "done when" condition is met, with the date and one line on anything that went differently.

## Starting state (2026-10-25)

- Repo cloned from `github.com/gabrielsgaspar/alteram` on Windows (`C:\Users\Gabriel Gaspar\Projects\alteram`); only the initial clone in git history.
- `AGENTS.md`, `CLAUDE.md` and `.claude/` are present locally but not yet committed or pushed.
- `.env` and `.env.example` already exist. `.env.example` uses different variable names from the brief (see step 3/4 notes). `.env` is covered by `.gitignore`.
- Git identity (`user.name`, `user.email`) appears unset.

## Steps

- [x] **1. Check prerequisites** — git, gh, uv, claude all print a version
  - Done 2026-10-25. Windows, so tools installed via winget rather than brew; git identity and `gh auth` also set up.
- [x] **2. Add the provided files** — `AGENTS.md`, `CLAUDE.md`, `.claude/` on GitHub
  - Done 2026-10-25 (commit 1f8dad1, pushed). Also added `ALTERAM_SETUP_BRIEF.md` to the repo root so Claude Code can read it; the old `.env.example` went in too and is replaced in step 3.
- [x] **3. Python project** — `uv run python -c "import langgraph, langchain_anthropic, pydantic"` runs
  - Done 2026-10-25 (commit 5234de8, pushed). `uv python install 3.12` hit a Windows link bug; project works without the `UV_PYTHON` workaround. Claude Code deleted a file in `%APPDATA%\uv` unasked: watch for changes outside the repo. Secrets decision: Option A (see Decisions).
- [x] **4. Accounts and keys** — `.env` exists, untracked, has all required variables
  - Done 2026-10-25. Old `.env` replaced from `.env.example`; dedicated spend-limited key; `LANGSMITH_TRACING=false` until step 9. Models confirmed current: lawyers `claude-sonnet-5-5`, judge `claude-opus-5-5` (Opus 5.5 thinking is always on, so the judge is non-deterministic too).
- [x] **5. Write three cases** — three cases in `cases/` pass `new-case` checks, `expected` filled in
  - Done 2026-10-25 (commit f222d7d, pushed). Cases drafted by Cowork at Gabriel's request, not written by him (differs from brief); Gabriel confirmed the `expected` values. Delivery dates added after review. `new-case` skill edits agreed (checks 3 and 5 tightened, check 8 added for parties in [1] and delivery date); Gabriel applies them through Claude Code, because Cowork can't write to `.claude/`. Claude Code first reviewed a stale copy of case-001: re-read from disk after outside edits.
- [x] **6. Draft the agent prompts** — Gabriel approved all three, each starts with `version: 1`
  - Done 2026-10-26, pushed. Gabriel approved Cowork's v1 drafts unchanged (brief asked for a rewrite in his own words). From here, his judgement enters through `prompt-change` decisions after step 9. `new-case` skill edits applied. Git warned LF→CRLF on Windows; `.gitattributes` added in step 7 so prompt hashes match across machines. v1 drafts by Cowork. Lawyer prompts differ only in side names (checked with diff). The decision standard is copied word for word into all three; propose a test in step 7 that keeps it identical. Prompts assume point labels (C1, R1…), a strongest-counterpoint field, and missing-fact and what-would-change fields, which the section 5 schema lacks; to add in step 7.
- [x] **7. Data models and case loader** — `uv run pytest` passes
  - Done 2026-10-26 (commits 8224efa, 93a6579): 43 tests pass, ruff clean; Cowork re-ran both on Linux too. Added beyond the original brief: point labels and side set by code, label checks, unsupported-claim label check, case hash, judge order, LF line endings via `.gitattributes`. Four commits were left unpushed while Gabriel was away.
- [x] **8. The graph** — tests pass; Gabriel can explain each node's inputs and outputs
  - Done 2026-10-26 (commit 3b9cbc7, pushed). Cowork wrote the node-by-node explanation with line references; Gabriel confirmed he can explain it. Details: 55 tests pass, ruff clean (re-run on Linux by Cowork). Phase 1 findings checked against the Anthropic docs: thinking can't be disabled; `display: "summarized"` is needed and returns only a summary; forced `tool_choice` is a 400, so structured outputs via `output_config.format`, no conversion call. Effort `high` for all agents, `max_tokens` 32000; refusal and max_tokens stops are hard failures; parse and check failures retried once. Carried to step 9: declare `anthropic` in pyproject (imported directly, currently only transitive); log the rejected attempt's error; judge-only entry point so swap reuses the same arguments; save failed runs.
- [x] **9. Command line and run logs** — all three cases run, review notes written below
  - Done 2026-10-26. CLI built ("Add CLI with run logs and order-swap check", tracing forced off in tests); `anthropic` declared in pyproject. One `run` per case plus `swap --repeats 5` on all three. Total cost about $3 from logged tokens. One-sided case won, no order flips, so no prompt change is required by the brief; one judge label defect to fix (see review notes).
- [x] **10. Continuous integration** — CI green on GitHub
  - Done 2026-10-28. `main` (commit 44184a8) pushed to GitHub; CI run green: https://github.com/gabrielsgaspar/alteram/actions/runs/40666729199.
- [x] **11. README** — README on GitHub
  - Done 2026-10-29 (PR from `docs/readme`; on GitHub once merged). Written by Claude Code, not Cowork; also covers `rejudge`, `eval` and the build → review harness, which came after the brief.
- [x] **12. Retrospective** — three answers recorded below, next item chosen
  - Done 2026-10-30. Answers below; next item is v1.

## Decisions

- **2026-10-25, `.env` protection: Option A.** On native Windows the Claude Code sandbox is unavailable, and `Read` deny rules don't cover scripts that open files themselves or commands like `grep -r`. Accepted: keep the deny rules and the `AGENTS.md` rule, and use a dedicated, spend-limited Anthropic key that's revoked if it ever appears in output. Revisit (WSL2 + sandbox `denyRead`) before handling any real party data.
- **2026-10-25, decision standard: Financial Ombudsman style.** The judge decides what is fair and reasonable, taking relevant law into account, with facts found on the balance of probabilities. The law stated in the prompts is a short Consumer Rights Act 2015 summary: satisfactory quality (judged by age, mileage and price); a fault appearing within 6 months of delivery is presumed present at delivery unless the business shows otherwise, after that the consumer must show it; 30-day short-term right to reject; then one repair or replacement before rejection or price reduction. Draft summary, not legal advice; check against the Act before step 6.
- **2026-10-25, meaning of `undecidable`:** a fact the decision turns on is missing, and a fair adjudicator would ask for it before deciding. Missing facts otherwise fall on whoever has to prove them.
- **2026-10-26, Cowork wrote code at Gabriel's request.** This overrides the standing rule that Claude Code writes all code, for one change only: the judge label fix in `validate.py` and its tests. Tested in the cloud workspace (71 tests, ruff clean) before it was written to the repo.
- **2026-10-26, case-004 added.** A fourth case where the respondent should clearly win, because with three claimant-or-undecidable cases a judge that favours claimants can't be detected. Drafted by Cowork; `expected: respondent` set by Cowork at Gabriel's request. Committed before any run.
- **2026-10-25, respondent convention:** paragraph [1] of every case names the claimant and the respondent. Under conditional sale, the respondent is the finance company.
- 2026-10-27: WSL2 (Ubuntu 26.04.1 LTS, WSL 3.0.3.0) and Docker Desktop (4.97.0) installed; development moves to WSL2
- 2026-10-27: workspace moved to WSL2 at ~/projects/alteram; Windows copy retired.
- 2026-10-27: Bash sandbox enabled (WSL2, strict mode, `failIfUnavailable`) with OS-level `denyRead` on `.env` paths and `**/.env`; network limited to PyPI and GitHub, write added for `~/.cache/uv`. Verified with a canary file that cat/head/grep/python/uv-run reads fail, and uv sync/lock, ruff, pytest (107 passed), git and gh work sandboxed.
- 2026-10-30: v0 closed (setup steps 1–12 done). Next: v1 per docs/ALTERAM_V1_DESIGN.md, milestones M3, M4, M5, then M2, design defaults accepted 2026-10-29.
- **2026-11-01, M3 decisions D1–D9** (Gabriel; full table in `docs/milestones/M3.md` section 10):
- 2026-11-01, D1: a CLI inspector (`alteram law show/search/status`) in M3 (step 16); the console view stays in M2.
- 2026-11-01, D2: FCA route (a). Gabriel emails the FCA (handbook.feedback@fca.org.uk) for written consent to automated download and storage in a retrieval system, and the statute track runs meanwhile. Fallback: if there is no answer by step 17, FCA is deferred from M3 (option c).
- 2026-11-01, D3: FCA chapters CONC 1, 5, 6, 7 and DISP 1, 2, 3. No PRIN 2A.
- 2026-11-01, D4: CCA 1974 sections 56, 87–90, 99, 100, 140A–140C and 173. Sections 75 and 75A are left out: under hire purchase and conditional sale the finance company is the supplier, so s.75 doesn't apply. They are a candidate negative case for M4's citation checker.
- 2026-11-01, D5: the Limitation Act 1980 (ss.2, 5, 14A, 32) is a third M3 source, `limitation-1980`.
- 2026-11-01, D6: law data models live in `law/models.py`; only `ContextualHeader` goes in `src/alteram/models.py`, as `AGENTS.md` requires.
- 2026-11-01, D7: paid `law` commands take a `--budget` flag (default $5), separate from `ALTERAM_RUN_BUDGET_USD`.
- 2026-11-01, D8: PostgreSQL 18 instead of the design's 16; built-in full-text search in M3; BM25 (pg_textsearch, custom image) is decided in M4 on recall@k.
- 2026-11-01, D9: a Postgres service in CI; step 10 edits `.github/workflows/ci.yml`.
- 2026-11-01: the old local branch `plan/M3-2026-10-30` is superseded by `docs/milestones/M3.md`.
- 2026-11-01: `www.legislation.gov.uk` stays out of `.claude/settings.json`, because the GitHub agent workflows load project settings too. Gabriel runs the fixture `curl` commands and every later network, Docker and paid command in his own terminal.
- 2026-11-01: M3 step 01 adds `alembic`, `psycopg[binary]` and `httpx` (approved by Gabriel), the seven new environment variables, the `law/` ignore rules, and the legislation.gov.uk fixtures.

## Step 9 review notes

_Cases where the judge disagreed with `expected`, flipped on swap, or let an unsupported claim through._

**First real runs, 2026-10-26** (prompts v1, `claimant_first`, one run each; swaps not yet run):

- **case-001** (`runs/case-001/20261026T205844Z.json`): claimant, confidence 0.92, matches `expected`. All agents took one attempt and stopped normally. Judge correctly rejected R3's repair-first argument (no repair-first rule within 30 days) and flagged C4's "failure to repair within a reasonable time" as unsupported. Claimant lawyer returned no thinking (adaptive skip). Minor: R1 cites [2], which doesn't support its point, and the judge didn't flag it.
- **case-002** (`runs/case-002/20261026T210410Z.json`): claimant, confidence 0.72, matches `expected` (Cowork's narrow call). Judge caught C5's unsupported "has not offered a repair". To watch: (1) possible asymmetry, since the judge flagged R2's "high-mileage" as unsupported even though [4] and [8] show 19,600 miles in 7 months, while accepting the claimant's inferences; (2) the judge added its own technical theory ("a progressive problem caused by restricted oil flow") to reject R4, which isn't in the case or either argument; (3) neither lawyer, nor the judge, noted that Fenwick Motors both diagnosed the fault and quoted for the repair; (4) the case may lean further to the claimant than its `balanced` label suggests, because [13] (inspector silent on the pipe) is strong. Not changing the case after seeing results; the swap runs will show whether 0.72 is stable.
- **Cost:** about $0.10–0.12 per run from logged tokens, about a third of Cowork's estimate. Confirm in the Console.

**Swap checks, 2026-10-26** (prompts v1, `--repeats 5`, the same two arguments for all 10 judge calls per case):

| Case | `expected` | Winners (claimant_first / respondent_first) | Mean confidence | Within / across disagreement |
| --- | --- | --- | --- | --- |
| 001 | claimant | 5 claimant / 5 claimant | 0.91 / 0.92 | 0.0 / 0.0 |
| 002 | claimant | 5 claimant / 5 claimant | 0.72 / 0.72 | 0.0 / 0.0 |
| 003 | undecidable | 5 claimant / 3 claimant, 2 undecidable | 0.60 / 0.55 | 0.3 / 0.4 |

- **No order effect.** Cases 001 and 002 never moved. In case 003, across-order disagreement (0.4) is barely above within-order (0.3); the two `undecidable` verdicts both came in respondent_first, but 5/5 vs 3/5 is well within chance (Fisher p ≈ 0.44).
- **Case 003 misses `expected` in 8 of 10, but the judge found the crux in 10 of 10.** Every verdict named the job card as the fact that would change the outcome. The claimant wins rest on two drafting choices in the case (Cowork's): [9] is a non-denial ("the first report it knows of"), and the job card sits with the dealer, the respondent's side, so an adverse inference against the respondent is reasonable. Confidence of 0.45–0.62 shows the judge treated it as close. Verdict: a case design weakness more than a judge failure. `expected` stays as pre-registered; a better missing-fact case goes in a new file, not an edit of 003.
- **Defect: judge labels.** In case 001, 4 of 10 judge calls needed a retry because the judge tried to flag the requested outcome as unsupported, using labels like "C (requested outcome)" that don't exist. Requested outcomes and strongest-point-against answers have no labels. Fix in code and in the judge prompt (v2) through `prompt-change`.
- **Possible asymmetry, untestable with these cases.** Respondent points were flagged unsupported far more often than claimant points (case 002: 33 vs 0 across 10 verdicts). But the claimant should win all three cases, so the losing side's stretching and a pro-claimant judge look the same. A case where the respondent should clearly win is needed to tell them apart.
- **Judge v2 runs, 2026-10-26 22:04–22:13** (commit 5c2c1f7; details in `docs/prompt-log.md`): case-004 went to the respondent 10/10 at confidence 0.90, so the judge does find against a consumer. In case-004 the claimant's points were flagged unsupported far more (25 vs 6). The earlier asymmetry therefore follows the losing side, not the claimant. v2 introduced a new retry cause (reasons for `C-against`/`R-against`, 24 of 40 calls); the fix is in code.
- **What the swap measures.** With fixed arguments the judge is very stable (case 002: 0.72 on all 10). Run-to-run variation therefore comes mostly from the lawyers, which the swap check doesn't vary.
- **M1 baseline, 2026-10-29** (`eval/baselines/20261029T185846Z.json`): 83% [50%, 100%], case-003 the only miss (claimant 2, undecidable 1), 0% retries, $0.12 per run.

## Retrospective

- Hardest part: Keeping one working copy. The repo existed in Windows, in WSL and in a mirror; Claude Code kept running in /mnt/c, which caused mode noise and blocked checkouts; and an rsync --delete wiped the unpushed harness, which had to be recovered from a transcript. Fixed with the WSL rule, the claude guard and a read-only mirror without .git.
- What I'd hand to Claude Code differently: Start every session with the working directory and a task file with acceptance criteria, and push branches straight away so nothing lives in one copy. Paid API runs happen in my own terminal, because the sandbox blocks the Anthropic API.
- Most surprising result from step 9: With fixed arguments the judge barely moved (case 002 got 0.72 on all 10 calls), so run-to-run variation comes from the lawyers. Case 003 missed its expected verdict in 8 of 10 calls, yet the judge named the missing job card in all 10: a weakness in how the case was written, not in the judge.
- Next item from section 10: v1 per docs/ALTERAM_V1_DESIGN.md: M3, M4, M5, then M2; design defaults accepted (decided 2026-10-29).
