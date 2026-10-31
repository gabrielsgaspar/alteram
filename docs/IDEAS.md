# Ideas after v0

Things suggested during setup that are outside v0. Each is a separate piece of work for after section 8 is done; see `ALTERAM_SETUP_BRIEF.md` section 10 for the planned order.

- **Remedy in the verdict (2026-10-25).** v0's judge picks only a winner. A real decision also says what the respondent must do: reject and refund, repair, a price reduction, or a deduction for use. Add a `remedy` field to `Verdict` and score it separately.
- **Harder missing-fact cases (2026-10-25).** Case 003 points to its missing document explicitly ([8]). Add cases where the decisive fact is absent without being flagged.
- **Paired re-judging (2026-10-26). Done 2026-10-27.** An `alteram rejudge <run or swap file>` command that runs the current judge prompt on the arguments saved in an earlier run. Judge prompt changes can then be compared on identical inputs, which is the paired experiment in brief section 3. The judge v1 → v2 comparison on case-003 was confounded without it.
- **Repeated full runs (2026-10-26).** The swap check holds the arguments fixed, and the judge is then nearly deterministic. Re-run the whole graph several times per case to measure how much verdicts vary because the lawyers argue differently.
- **Cases not written by Claude (2026-10-25).** The v0 cases were drafted by Claude, which also argues and judges them. Add cases written by people, and later real ombudsman decisions (section 10, item 3).
- **LangSmith Studio (2026-10-26).** An interactive view of the graph that can re-run individual nodes. It needs `langgraph-cli` as a dev dependency, a `langgraph.json`, and graph inputs Studio can build (today the state holds a `Case` object). It's useful for learning LangGraph once loops and human-in-the-loop pauses arrive; v0 uses LangSmith tracing instead.
- **WSL2 and sandbox for `.env` (2026-10-25).** Move development to WSL2 so the Claude Code sandbox can block every read of `.env`. Do this before any real party data is used.
- **Independent ground truth (2026-10-29).** Cases 001–009 are all Claude-written, so eval agreement partly measures Claude agreeing with itself. Bring a small set of Financial Ombudsman decisions forward from M10 once the reuse terms are confirmed, or add human-written cases.
- **Agent workflow checks as tested code (2026-10-31).** Follow-ups from the PR #16 reviews of `agent-build.yml`:
  1. Move the path check, secret scan, binary check and gitlink check out of inline YAML into `scripts/agent_checks.py`, with a pytest case for every attack raised in the PR #16 reviews, so CI re-tests them on every change. Start from the harness in `~/alteram-drafts/agent-checks-harness`.
  2. Reject `CLAUDE.md`, `AGENTS.md` and files under `.claude/` at any depth unless the approved plan names the exact path.
  3. Run verify's pytest without sudo and without network access.
  4. Protect the artifact handoff between build, verify and publish, so a `plan.md` swapped in the artifact can't change the PR body.
  5. Refuse added lines that contain NUL bytes, and let the secret scan accept signed commits.
  6. Close the remaining risk that code run in the agent workflows poisons the uv cache `ci.yml` restores.
  7. Add actionlint to CI.
