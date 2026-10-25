---
name: prompt-change
description: Required procedure for any change to an Alteram agent prompt in prompts/ (claimant, respondent or judge). Use this whenever a prompt file is edited, a prompt change is proposed, or a run result suggests the prompts need fixing, so every change is versioned and tested on all cases.
---

# Prompt change

Prompts are the product. A change that improves one case can break another, so every change is versioned, run on every case and logged.

## Procedure

1. **State the reason.** Write one sentence on what problem the change fixes, citing the run file that shows it.
2. **Make the change.** Edit the prompt and increment its `version:` line by one.
3. **Keep the lawyers mirrored.** If you change `claimant.md`, make the matching change to `respondent.md`, unless the owner says the difference is deliberate. Show both diffs.
4. **Run every case.** Run `uv run alteram run` and `uv run alteram swap` on every file in `cases/`, not just the one that prompted the change.
5. **Compare.** For each case, compare with the most recent run on the previous version: verdict, confidence, whether it matches `expected`, whether the swap check flipped, and any unsupported claims.
6. **Log it.** Append an entry to `docs/prompt-log.md`:

```markdown
## YYYY-MM-DD: judge.md v2 → v3
Reason: …
Change: …
Results: case-001 unchanged; case-002 now undecidable (was respondent); swap flips 1 of 3 → 0 of 3
Decision: kept | reverted (owner)
```

7. **Ask the owner.** Show the log entry and ask whether to keep or revert. Do not commit a prompt change without the owner's approval.

## Never

- Never change a prompt as a side effect of another task.
- Never tune a prompt to one case's `expected` value while other cases get worse.
