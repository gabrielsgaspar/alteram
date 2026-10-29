# Prompt change log

One entry per prompt change, following `.claude/skills/prompt-change/SKILL.md`.

## 2026-10-26: judge.md v1 → v2

Reason: in `runs/case-001/20261026T211057Z-swap.json`, 4 of 10 judge calls were rejected and retried. The judge tried to flag a requested outcome as unsupported, using labels that don't exist ("C (requested outcome)", "C1/requested outcome"). Requested outcomes and answers to the strongest point against had no labels.

Change:
- `prompts/judge.md`: version 2. One sentence added to the "Unsupported claims" output bullet: for a side's requested outcome or its answer to the strongest point against, use `C-outcome`, `C-against`, `R-outcome` or `R-against`.
- `src/alteram/validate.py`: `check_unsupported_labels` accepts those four labels (in `unsupported_claims` only; reasons still cover numbered points). Its rejection message now lists them, so a retry knows what to use.
- Lawyer prompts unchanged, so the mirror rule is unaffected.
- Made by Cowork at Gabriel's request, not by Claude Code.

Results (`swap --repeats 5`; v1 runs 2026-10-26 21:10–21:22, v2 runs 22:04–22:13; mean confidence given as claimant_first / respondent_first):
- case-001: v1 claimant 10/10, 0.91 / 0.92, 4 judge retries → v2 claimant 10/10, 0.86 / 0.86, 5 judge retries.
- case-002: v1 claimant 10/10, 0.72 / 0.72, 0 retries → v2 claimant 10/10, 0.74 / 0.74, 10 retries.
- case-003: v1 claimant 8/10, undecidable 2/10 → v2 undecidable 8/10, claimant 2/10, 8 retries. Confounded: each swap re-runs the lawyers, and the v2 respondent argument had 1 point against 4 in v1. The shift can't be attributed to the prompt.
- case-004 (new, v2 only): respondent 10/10, 0.90 / 0.90, 1 retry.
- Retries: the old error ("C (requested outcome)") is gone, but a new one replaced it. The judge now also writes reasons for `C-against` and `R-against`, which `check_reason_coverage` rejects as unknown. 24 of 40 v2 judge calls retried, against 4 of 30 in v1. The v2 sentence caused this.
- Order: no order effect in any case. In case 003 the minority verdicts came only in respondent_first in both versions (4/20 vs 0/20, Fisher p ≈ 0.11): watch, not act.

Decision: keep v2 (recommended by Cowork; owner to confirm), with a code fix so reasons may also cover the four part labels, which are optional and never required. No v3 prompt needed.

Code fix: part labels allowed as optional reasons (commit 58e5b0b)

Method note: comparing judge prompts with `swap` re-runs the lawyers, so lawyer variation is mixed into the comparison. A clean comparison re-judges the same saved arguments under both judge versions (see `docs/IDEAS.md`).

## 2026-10-29: M1 baseline recorded (no prompt change)

Baseline: `eval/baselines/20261029T185846Z.json`, from `uv run alteram eval --n 3` (run by Gabriel; 4 cases × 3 = 12 runs, judge order alternating). Later prompt changes are compared against this with `alteram eval compare`.

Setup: lawyers `claude-sonnet-5-5`, judge `claude-opus-5-5`. Prompts: claimant v1 `46da619a`, respondent v1 `571c8702`, judge v2 `ec6effdf` (with the reasons fix in 58e5b0b).

Results:
- Accuracy against `expected`: 83%, 95% interval over cases [50%, 100%]. Only 4 cases, so the interval is wide.
- case-001 claimant 3/3 (0.89), case-002 claimant 3/3 (0.74), case-004 respondent 3/3 (0.87).
- case-003 (missing-fact, expected undecidable): claimant 2, undecidable 1 (mean 0.58). The two claimant verdicts came one in each order, so there is no order effect. Same weakness as in the v1/v2 swap runs above: the judge does not reliably return `undecidable` when a key fact is missing.
- Runs: 12 completed, 0 failed, 0 budget stops.
- Retries: 0% for every agent, compared with 24 of 40 judge calls in the v2 swap runs before 58e5b0b.
- Cost: $1.43 in total, $0.12 per run (dry-run estimate $1.63).

This closes milestone M1.
