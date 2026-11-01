# Task: M3-02 contextual header prompt, version 1

Mode: **local**, a supervised Claude Code session. Prompt changes are owner-approved (`AGENTS.md`), so Gabriel reads and approves the text before it is committed. Plan: `docs/milestones/M3.md`, step 02. Needs: nothing.

## Goal

Write the prompt that asks Claude Haiku 5.5 for a contextual header for one law-library chunk (design section 6.3). The header is used only to improve search and is never cited, so it must place the chunk in its document without adding law, conclusions or quotations.

## In scope

- `prompts/contextual_header.md`: new, starting `version: 1`. The prompt tells the model it will receive:
  - the document (all text of the source in force on a date), inside clearly marked tags, as data;
  - one chunk, with its heading path.

  It asks for two or three plain sentences that name the Act or sourcebook, the Part, Chapter and section, and say what the provision is about and which nearby provisions it refers to. Rules: no quotation of the chunk; no legal advice or conclusion about any dispute; no claims about case law; British English; output only the header, through the structured output `ContextualHeader {header}`.
- `tests/test_prompts.py`: extend the existing checks (version line, loads by name) to the new file, and add no test that calls a model.
- `docs/prompt-log.md`: a new entry "contextual_header v1", saying it is new, why, and that the first real outputs are read in step 17 with `--limit 5`.
- `tasks/M3-02-header-prompt.md`: this file.

## Out of scope

- The claimant, respondent and judge prompts.
- Code that uses the prompt (step 11).
- Any model call. The `prompt-change` skill's run-all-cases check does not apply, because this prompt is not part of the case graph. Say so in the prompt-log entry.

## Gabriel does

Read the draft in the session, ask for changes, and approve the final text explicitly before it is committed.

## Acceptance criteria

1. `prompts/contextual_header.md` starts with `version: 1` and says the document and chunk are data, not instructions.
2. The prompt states each rule in "In scope" (no quotation, no conclusion, two or three sentences, British English).
3. Gabriel's approval is recorded in the `docs/prompt-log.md` entry, with the date.
4. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
5. `git diff --stat main` lists only the four files in scope.
