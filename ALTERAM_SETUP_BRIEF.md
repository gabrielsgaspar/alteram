# Alteram: setup brief

This file is the single source of truth for setting up Alteram v0. It is written to be handed to Claude Cowork, which guides Gabriel through the setup step by step. Everything here is decided unless marked as open.

---

## 0. Instructions for Claude Cowork

You are Gabriel's setup guide for this repository. Your job is to get Alteram v0 from an empty cloned repo to a working run: two AI lawyers argue a written case, an AI judge decides, and the result is saved.

How to work:

1. **One step at a time.** Work through section 8 in order. For each step, say what it is for, what Gabriel does himself, and what (if anything) he should hand to Claude Code. Wait for Gabriel to confirm a step is done before moving on.
2. **Keep a log.** Create `docs/SETUP_LOG.md` at the start: one checkbox per step from section 8. Tick each step when Gabriel confirms it, with the date and one line on anything that went differently.
3. **You write documents; Claude Code writes code.** You write and edit Markdown: `README.md`, the agent prompts in `prompts/`, `docs/`, and case files in `cases/`. Do not write Python, TOML, YAML or shell scripts yourself. For those, give Gabriel the Claude Code prompt from the step, adapted to what has happened so far. Gabriel is deliberately learning to drive Claude Code.
4. **Secrets never pass through chat.** Never ask Gabriel to paste an API key into the conversation. Tell him which variable to add to `.env`, and how, and let him do it. Never open, read or print `.env`. If a key appears in chat by accident, tell him to revoke it in the provider's console and create a new one.
5. **Challenge, don't just comply.** Gabriel prefers critical feedback. If a step, prompt or case looks weak, say so and say why, then suggest a fix.
6. **Stay inside v0.** If Gabriel or a tool suggests features from section 10, note them in `docs/IDEAS.md` and carry on. v0 is done when section 8 is done.
7. **Check facts that change.** Tool versions, model IDs and API parameters change. When a step depends on one, tell Gabriel to have Claude Code check the current official docs rather than trusting this file.

Files already provided and to be copied into the repo in step 2: `AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`, `.claude/skills/new-case/SKILL.md`, `.claude/skills/prompt-change/SKILL.md`. Do not rewrite them unless Gabriel asks.

---

## 1. What Alteram is

Alteram is an AI adjudication system for small disputes. The name comes from *audi alteram partem*, "hear the other side", a core rule of natural justice in English law.

In the full vision, two parties describe a dispute, agree on what is actually in dispute, and each is represented by an AI advocate. An AI adjudicator writes a reasoned decision that ties every finding to evidence and to the legal test. A panel of different models checks the decision, and uncertain cases go to a human. The system is scored in public against real decisions by the Financial Ombudsman Service.

v0 is much smaller (section 4). It exists to get the core loop working and measurable.

## 2. Aims and non-goals

Aims, in order:

1. **Learning.** Alteram is first a vehicle for Gabriel to learn agent orchestration, Claude Code, Google Cloud and web delivery on a real problem.
2. **A result that can be checked.** Every output is structured, logged and reproducible, so it can be tested and compared rather than admired.
3. **A narrow domain done well.** The long-term target is UK consumer disputes about faulty cars bought on finance, measured against ombudsman decisions.

Non-goals for v0: money, users, a website, cloud deployment, retrieval, web search, evidence uploads, rebuttals, review panels, and any claim that outputs are legal advice or binding.

## 3. What Gabriel wants to learn

- **Agent orchestration with LangGraph:** typed state, parallel branches, then later loops, checkpoints and human-in-the-loop pauses.
- **Claude Code as an implementation agent:** writing good prompts, keeping standing rules in `AGENTS.md` and `CLAUDE.md`, using skills, and later a builder → tests → reviewers → aggregator loop that produces production-grade code.
- **Evaluation:** checking agent outputs with tests and paired experiments, not by reading a few and feeling good.
- **Later:** Google Cloud (Cloud Run, Cloud Storage, Cloud SQL, Pub/Sub, Vertex AI, Terraform) and a Next.js website.

## 4. v0 scope

v0 does exactly this:

1. Read a written case from `cases/<id>.md`: a short neutral account of what happened, in numbered paragraphs.
2. Two lawyer agents run in parallel, one for the claimant and one for the respondent. Each thinks privately (adaptive thinking), then writes an argument for its side. Every point must cite paragraph numbers.
3. A judge agent sees the case and both arguments, and writes a verdict: claimant, respondent or undecidable, with reasons per point, citations and a confidence score.
4. The full run is saved to `runs/` as JSON.
5. An order-swap check runs the judge twice with the arguments in opposite order and reports whether the verdict changes.

No retrieval, no web search, no rebuttal round, no human review in v0.

## 5. v0 design

### Case file format

```markdown
---
id: case-001
title: Gearbox fault on a car bought on conditional sale
kind: one-sided        # one-sided | balanced | missing-fact
expected: claimant     # Gabriel's own view; for sanity checks only, never shown to agents
---

[1] On 3 March 2026 Ms A bought a used car from Northway Motors, financed by a conditional sale agreement with Brightline Finance.
[2] The car had 41,200 miles on the clock at supply.
...
```

The `[n]` markers are how agents cite facts. Agents never see the frontmatter.

### Data models (Pydantic)

- **Case:** `id`, `title`, `paragraphs` (number → text). `kind` and `expected` are loaded for checks but never sent to an agent.
- **Argument:** `side` (claimant | respondent), `points` (each: claim, reasoning, cited paragraph numbers, which must be non-empty), `requested_outcome`.
- **Verdict:** `winner` (claimant | respondent | undecidable), `reasons` (each: the point it addresses, finding, cited paragraph numbers), `unsupported_claims` (points from either side whose citations don't support them), `confidence` (0 to 1).
- **Run:** case id, both arguments, the verdict, lawyer thinking (logged only), model IDs, a hash of each prompt file, timestamps, token counts.

Code-level rule: a citation to a paragraph that does not exist is rejected before the judge sees it.

### Graph (LangGraph)

```
START ──► claimant lawyer ──┐
     └──► respondent lawyer ─┴──► judge ──► END
```

- The two lawyers run in parallel and never see each other's argument in v0.
- Lawyers use adaptive thinking. Their thinking is saved to the run log and **never** passed to the judge.
- The judge sees the case text and the two arguments, in an order the code controls (needed for the order-swap check).
- Models come from environment variables. Starting values: lawyers `claude-sonnet-5-5`, judge `claude-opus-5-5`. Check current IDs in the Anthropic docs.
- If structured output and thinking conflict in the current API, lawyers write freely and a second cheap call converts their text to the `Argument` schema.

### Target repo layout after v0

```
alteram/
├── AGENTS.md              # standing rules for coding agents (provided)
├── CLAUDE.md              # Claude Code entry point, imports AGENTS.md (provided)
├── README.md              # written by Cowork in step 11
├── .claude/
│   ├── settings.json      # blocks agents from reading .env (provided)
│   └── skills/            # new-case, prompt-change (provided)
├── .env                   # Gabriel creates; never committed
├── .env.example           # variable names only
├── .github/workflows/ci.yml
├── pyproject.toml
├── cases/                 # case-001.md … case-003.md
├── prompts/               # claimant.md, respondent.md, judge.md
├── docs/                  # SETUP_LOG.md, IDEAS.md, prompt-log.md
├── runs/                  # run JSON files; gitignored
├── src/alteram/           # models, graph, cli
└── tests/
```

## 6. Tools

| Tool | What it does | How to get it |
| --- | --- | --- |
| Git and GitHub CLI (`gh`) | Version control, repo and CI from the terminal | `brew install gh`, then `gh auth login` |
| uv | Python versions, virtual environment and packages in one fast tool | `brew install uv` |
| Claude Code | Writes and runs the code | Already installed |
| Claude Console | Issues the API key the app uses; separate from Claude Code's plan | platform.claude.com; set a monthly spend limit |
| LangGraph + langchain-anthropic | The agent graph and the Claude model wrapper | Installed by Claude Code in step 3 |
| Pydantic | Typed inputs and outputs for every agent | Installed in step 3 |
| pytest, ruff | Tests and linting | Installed in step 3 |
| LangSmith (optional) | Visual traces of each graph run | smith.langchain.com, free developer tier |
| GitHub Actions | Runs tests on every push | Set up in step 10 |

## 7. Environment variables

Gabriel adds these to `.env` himself. `.env.example` lists the names with empty values.

| Variable | Required | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Yes | Calls to Claude from the app |
| `ALTERAM_LAWYER_MODEL` | Yes | Model ID for both lawyers |
| `ALTERAM_JUDGE_MODEL` | Yes | Model ID for the judge |
| `LANGSMITH_TRACING` | No | `true` to send traces to LangSmith |
| `LANGSMITH_API_KEY` | No | LangSmith key |
| `LANGSMITH_PROJECT` | No | e.g. `alteram-v0` |

---

## 8. Setup steps

Each step lists what Gabriel does, what Cowork does, the Claude Code prompt where code is needed, and how to know the step is done.

### Step 1: Check prerequisites

- **Gabriel:** run `git --version`, `gh --version`, `uv --version`, `claude --version` and report anything missing.
- **Cowork:** give install commands for anything missing (section 6). Create `docs/SETUP_LOG.md`.
- **Done when:** all four commands print a version.

### Step 2: Add the provided files

- **Gabriel:** copy `AGENTS.md`, `CLAUDE.md` and the `.claude/` folder into the repo root. Commit: `git add -A && git commit -m "Add agent instructions" && git push`.
- **Cowork:** read `AGENTS.md` and confirm it matches this brief. Flag any mismatch.
- **Done when:** the files are on GitHub.

### Step 3: Python project

- **Claude Code prompt:** *"Read AGENTS.md. Set up a uv project for Python 3.12 with package name alteram in src/alteram. Dependencies: langgraph, langchain-anthropic, pydantic, python-dotenv. Dev dependencies: pytest, ruff. Add a .gitignore covering .env, .venv, runs/ and caches. Add .env.example with the variable names from AGENTS.md and empty values. Do not read .env. Show me the plan before writing files."*
- **Gabriel:** review the plan, approve, then run `uv sync`.
- **Done when:** `uv run python -c "import langgraph, langchain_anthropic, pydantic"` runs without error.

### Step 4: Accounts and keys

- **Gabriel:** create an API key in the Claude Console and set a spend limit. Optionally create a LangSmith account and key. Create `.env` from `.env.example` and fill in the values in your editor. Run `git status` and confirm `.env` is not listed.
- **Cowork:** explain each variable from section 7. Never ask for the values.
- **Done when:** `.env` exists, is not tracked by git, and has all required variables.

### Step 5: Write three cases

- **Gabriel:** write three short cases (8 to 15 paragraphs each) in your own words: one clearly one-sided, one balanced, one missing a fact the decision turns on. Follow the format in section 5. Claude Code's `new-case` skill can check the format.
- **Cowork:** critique each case. Look for loaded wording, conclusions disguised as facts ("the dealer obviously lied"), and paragraphs that mix two facts. Suggest neutral rewrites.
- **Done when:** three cases in `cases/` pass the `new-case` checks and Gabriel has filled in `expected` for each.

### Step 6: Draft the agent prompts

- **Cowork:** draft `prompts/claimant.md`, `prompts/respondent.md` and `prompts/judge.md` with Gabriel, following section 9. Then ask Gabriel to rewrite them in his own words: the prompts are the product, and the drafts are only a start.
- **Done when:** Gabriel has approved all three, and each starts with `version: 1`.

### Step 7: Data models and case loader

- **Claude Code prompt:** *"Following AGENTS.md and the data models in ALTERAM_SETUP_BRIEF.md section 5, create Pydantic models for Case, Argument, Verdict and Run in src/alteram/models.py, and a loader that reads cases/*.md into Case objects. Reject arguments that cite paragraphs that don't exist. Write pytest tests for the loader and the citation check."*
- **Done when:** `uv run pytest` passes.

### Step 8: The graph

- **Claude Code prompt:** *"Build the v0 LangGraph StateGraph described in ALTERAM_SETUP_BRIEF.md section 5: claimant and respondent lawyers in parallel, both feeding a judge. Load prompts from prompts/. Read model IDs from environment variables. Lawyers use adaptive thinking; save their thinking to the run state but never pass it to the judge. Check the current Anthropic and LangChain docs for how adaptive thinking and structured output work together, and tell me what you found before implementing. Add tests using LangChain's fake chat model so no test calls the real API."*
- **Gabriel:** read Claude Code's summary of the docs before approving. Ask it to explain anything unclear: this is the core thing you're learning.
- **Done when:** tests pass, and Gabriel can explain what each node receives and returns.

### Step 9: Command line and run logs

- **Claude Code prompt:** *"Add a CLI: `uv run alteram run cases/case-001.md` runs the graph, prints both arguments and the verdict in readable form, and saves the full Run as JSON in runs/<case-id>/<timestamp>.json. Add `uv run alteram swap cases/case-001.md`, which runs the judge twice with the arguments in opposite order and reports whether the verdict or confidence changed."*
- **Gabriel:** run both commands on all three cases. Read every argument and verdict in full.
- **Cowork:** help Gabriel review the outputs against `expected`. Note in `docs/SETUP_LOG.md` any case where the judge disagreed with `expected`, flipped on swap, or let an unsupported claim through.
- **Done when:** all three cases have run, and the review notes are written. If the one-sided case loses or verdicts flip, use the `prompt-change` skill to fix the prompts before moving on.

### Step 10: Continuous integration

- **Claude Code prompt:** *"Add a GitHub Actions workflow in .github/workflows/ci.yml that installs uv, runs `uv sync`, `uv run ruff check` and `uv run pytest` on every push and pull request. Tests must not need any secret. Commit and push."*
- **Gabriel:** open the Actions tab on GitHub and confirm the run is green.
- **Done when:** CI passes on GitHub.

### Step 11: README

- **Cowork:** write `README.md`: what Alteram is (two sentences), what v0 does, setup in five commands, how to run a case and the swap check, the folder layout, and an explicit line that outputs are not legal advice. Keep it short; link to this brief for detail.
- **Gabriel:** read it as if you were new to the project, then commit and push.
- **Done when:** the README is on GitHub.

### Step 12: Retrospective

- **Cowork:** ask Gabriel three questions and record the answers in `docs/SETUP_LOG.md`: what was hardest, what he would hand to Claude Code differently next time, and which result from step 9 surprised him. Then propose the first item from section 10 to start next.

---

## 9. Requirements for the agent prompts

All three prompts:

- Start with a `version:` line, incremented on every change (see the `prompt-change` skill).
- Rely only on the case text. No outside facts, no assumed law beyond what the prompt states.
- Use plain English.

Lawyer prompts (claimant and respondent):

- Argue only for your own side, as strongly as the facts honestly allow.
- Every point cites one or more paragraph numbers. Never invent facts or quote text that isn't in the case.
- Name the strongest point against your side and answer it.
- State the outcome you ask for.
- The two prompts should be mirror images. Any difference beyond the side's name is a bias risk; note it in the prompt if it's deliberate.

Judge prompt:

- Decide from the case text and the two arguments only.
- Address every point from both sides. For each, say whether the cited paragraphs support it.
- List unsupported claims separately; they count for nothing.
- Choose `undecidable` when the case lacks a fact the decision turns on, and name that fact.
- Give a confidence score, and explain what would change the decision.
- Ignore length, tone, confidence and eloquence. Only supported points count.

## 10. After v0 (not now)

In rough order, each one a separate piece of work:

1. A rebuttal round: each lawyer answers the other once.
2. A rule validator in code, plus a panel of reviewers from different model families.
3. Real ground truth: ombudsman decisions on car finance quality complaints, a frozen test set, and an evaluation in Inspect.
4. The build harness: builder → tests and linters → reviewer agents → aggregator → back to builder.
5. Google Cloud: Cloud Run, Cloud Storage, Cloud SQL, Pub/Sub, Vertex AI, Terraform.
6. A Next.js website: the case runner, case file and scorecard.
7. Live mode: the eligibility check, the agreement step on what is disputed, and the settlement room.

The full product specification and user flow live in a separate Claude Doc ("Docket — Product Specification", now Alteram).
