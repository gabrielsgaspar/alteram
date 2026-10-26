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
- [ ] **9. Command line and run logs** — all three cases run, review notes written below
  - Notes:
- [ ] **10. Continuous integration** — CI green on GitHub
  - Notes:
- [ ] **11. README** — README on GitHub
  - Notes:
- [ ] **12. Retrospective** — three answers recorded below, next item chosen
  - Notes:

## Decisions

- **2026-10-25, `.env` protection: Option A.** On native Windows the Claude Code sandbox is unavailable, and `Read` deny rules don't cover scripts that open files themselves or commands like `grep -r`. Accepted: keep the deny rules and the `AGENTS.md` rule, and use a dedicated, spend-limited Anthropic key that's revoked if it ever appears in output. Revisit (WSL2 + sandbox `denyRead`) before handling any real party data.
- **2026-10-25, decision standard: Financial Ombudsman style.** The judge decides what is fair and reasonable, taking relevant law into account, with facts found on the balance of probabilities. The law stated in the prompts is a short Consumer Rights Act 2015 summary: satisfactory quality (judged by age, mileage and price); a fault appearing within 6 months of delivery is presumed present at delivery unless the business shows otherwise, after that the consumer must show it; 30-day short-term right to reject; then one repair or replacement before rejection or price reduction. Draft summary, not legal advice; check against the Act before step 6.
- **2026-10-25, meaning of `undecidable`:** a fact the decision turns on is missing, and a fair adjudicator would ask for it before deciding. Missing facts otherwise fall on whoever has to prove them.
- **2026-10-25, respondent convention:** paragraph [1] of every case names the claimant and the respondent. Under conditional sale, the respondent is the finance company.

## Step 9 review notes

_Cases where the judge disagreed with `expected`, flipped on swap, or let an unsupported claim through._

## Retrospective

- Hardest part:
- What I'd hand to Claude Code differently:
- Most surprising result from step 9:
- Next item from section 10:
