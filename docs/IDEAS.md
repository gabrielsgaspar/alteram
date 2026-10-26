# Ideas after v0

Things suggested during setup that are outside v0. Each is a separate piece of work for after section 8 is done; see `ALTERAM_SETUP_BRIEF.md` section 10 for the planned order.

- **Remedy in the verdict (2026-10-25).** v0's judge picks only a winner. A real decision also says what the respondent must do: reject and refund, repair, a price reduction, or a deduction for use. Add a `remedy` field to `Verdict` and score it separately.
- **Harder missing-fact cases (2026-10-25).** Case 003 points to its missing document explicitly ([8]). Add cases where the decisive fact is absent without being flagged.
- **Repeated full runs (2026-10-26).** The swap check holds the arguments fixed, and the judge is then nearly deterministic. Re-run the whole graph several times per case to measure how much verdicts vary because the lawyers argue differently.
- **Cases not written by Claude (2026-10-25).** The v0 cases were drafted by Claude, which also argues and judges them. Add cases written by people, and later real ombudsman decisions (section 10, item 3).
- **LangSmith Studio (2026-10-26).** An interactive view of the graph that can re-run individual nodes. It needs `langgraph-cli` as a dev dependency, a `langgraph.json`, and graph inputs Studio can build (today the state holds a `Case` object). It's useful for learning LangGraph once loops and human-in-the-loop pauses arrive; v0 uses LangSmith tracing instead.
- **WSL2 and sandbox for `.env` (2026-10-25).** Move development to WSL2 so the Claude Code sandbox can block every read of `.env`. Do this before any real party data is used.
