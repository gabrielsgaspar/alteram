# Prompt change log

One entry per prompt change, following `.claude/skills/prompt-change/SKILL.md`.

## 2026-10-26: judge.md v1 → v2

Reason: in `runs/case-001/20261026T211057Z-swap.json`, 4 of 10 judge calls were rejected and retried. The judge tried to flag a requested outcome as unsupported, using labels that don't exist ("C (requested outcome)", "C1/requested outcome"). Requested outcomes and answers to the strongest point against had no labels.

Change:
- `prompts/judge.md`: version 2. One sentence added to the "Unsupported claims" output bullet: for a side's requested outcome or its answer to the strongest point against, use `C-outcome`, `C-against`, `R-outcome` or `R-against`.
- `src/alteram/validate.py`: `check_unsupported_labels` accepts those four labels (in `unsupported_claims` only; reasons still cover numbered points). Its rejection message now lists them, so a retry knows what to use.
- Lawyer prompts unchanged, so the mirror rule is unaffected.
- Made by Cowork at Gabriel's request, not by Claude Code.

Results (v1 baseline from the swap runs of 2026-10-26; v2 pending):
- case-001: v1 claimant 10/10, mean confidence 0.91 / 0.92, 4 judge retries. v2: pending.
- case-002: v1 claimant 10/10, 0.72 / 0.72, 0 retries. v2: pending.
- case-003: v1 claimant 8/10, undecidable 2/10, 0.60 / 0.55, 0 retries. v2: pending.
- case-004: new case, no v1 baseline. v2: pending.

Decision: pending (owner), after the v2 runs.
