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
- [ ] **2. Add the provided files** — `AGENTS.md`, `CLAUDE.md`, `.claude/` on GitHub
  - Notes:
- [ ] **3. Python project** — `uv run python -c "import langgraph, langchain_anthropic, pydantic"` runs
  - Notes:
- [ ] **4. Accounts and keys** — `.env` exists, untracked, has all required variables
  - Notes:
- [ ] **5. Write three cases** — three cases in `cases/` pass `new-case` checks, `expected` filled in
  - Notes:
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

## Step 9 review notes

_Cases where the judge disagreed with `expected`, flipped on swap, or let an unsupported claim through._

## Retrospective

- Hardest part:
- What I'd hand to Claude Code differently:
- Most surprising result from step 9:
- Next item from section 10:
