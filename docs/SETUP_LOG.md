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
- [ ] **5. Write three cases** — three cases in `cases/` pass `new-case` checks, `expected` filled in
  - Notes: cases drafted by Cowork at Gabriel's request rather than written by him (differs from brief). `expected` values are Cowork's; Gabriel to confirm or change before committing.
- [ ] **6. Draft the agent prompts** — Gabriel approved all three, each starts with `version: 1`
  - Notes:
- [ ] **7. Data models and case loader** — `uv run pytest` passes
  - Notes:
- [ ] **8. The graph** — tests pass; Gabriel can explain each node's inputs and outputs
  - Notes:
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
