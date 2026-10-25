---
name: new-case
description: Create, format or check an Alteram case file in cases/. Use this whenever the user adds a new case, edits a case, pastes a story about a dispute to turn into a case, or asks whether a case is well written, even if they don't say "case file".
---

# New case

A case is a short, neutral account of a dispute that both lawyer agents argue from and the judge decides on. Agents can only cite what is in it, so its quality limits everything downstream.

## Format

File: `cases/case-NNN.md`, numbered in order with three digits.

```markdown
---
id: case-NNN
title: One line describing the dispute, not the answer
kind: one-sided        # one-sided | balanced | missing-fact
expected: claimant     # claimant | respondent | undecidable; the owner's view, for checks only
---

[1] First fact.
[2] Second fact.
```

## Checks

Run each check and report every failure with the paragraph number and a suggested rewrite. Do not silently fix anything; the owner decides.

1. **Frontmatter:** all four fields present; `id` matches the file name; `kind` and `expected` use allowed values.
2. **Numbering:** paragraphs start at `[1]` and run without gaps or repeats.
3. **One fact per paragraph:** split paragraphs that state two separable facts, so citations stay precise.
4. **Neutral wording:** no conclusions dressed as facts ("obviously faulty", "the dealer lied"), no loaded adjectives, no legal conclusions ("this breached the contract").
5. **Both sides present:** each party's position appears as a reported claim ("Ms A says…", "Brightline says…"), not as the narrator's view.
6. **Kind matches content:** a `one-sided` case has clearly more support for one side; a `balanced` case has real support for both; a `missing-fact` case lacks a fact the decision turns on. Say which fact.
7. **Length:** 8 to 15 paragraphs. Flag anything outside that range.

## Never

- Never add facts the owner didn't provide.
- Never let `kind` or `expected` appear in the paragraphs.
