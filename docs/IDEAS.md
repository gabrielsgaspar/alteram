# Ideas after v0

Things suggested during setup that are outside v0. Each is a separate piece of work for after section 8 is done; see `ALTERAM_SETUP_BRIEF.md` section 10 for the planned order.

- **Remedy in the verdict (2026-10-25).** v0's judge picks only a winner. A real decision also says what the respondent must do: reject and refund, repair, a price reduction, or a deduction for use. Add a `remedy` field to `Verdict` and score it separately.
- **Harder missing-fact cases (2026-10-25).** Case 003 points to its missing document explicitly ([8]). Add cases where the decisive fact is absent without being flagged.
- **Cases not written by Claude (2026-10-25).** The v0 cases were drafted by Claude, which also argues and judges them. Add cases written by people, and later real ombudsman decisions (section 10, item 3).
- **WSL2 and sandbox for `.env` (2026-10-25).** Move development to WSL2 so the Claude Code sandbox can block every read of `.env`. Do this before any real party data is used.
