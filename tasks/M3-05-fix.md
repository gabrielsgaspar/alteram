# Task: M3-05 fix version merging (PR #34)

## Goal

Make merge_versions in src/alteram/law/chunk.py produce correct validity spans from real parser output. Parsing the committed CCA s.88 fixtures with parse_document and merging them shows two bugs. Unchanged provisions that are still in force get closed in 2008, and version dates from one Act close provisions of another.

## In scope

- `src/alteram/law/chunk.py`
- `tests/test_chunk.py`
- `tasks/M3-05-fix.md`

## Required behaviour

1. One span per run of identical text. It ends where the last version with that text ends (None if that version is open-ended), or where a later version of the same section changes, repeals or omits it. Today a later open-ended version with the same text does not reopen the span: s.88(1), (4) and (5), and the current wording of s.88(2) and (3), wrongly end on 2008-10-01.
2. A provision may be ended by absence only when a later version of the same section (same Act and section number) lacks it. Today, merging all fixture files together closes s.88(4A) on 2015-10-01, a date that exists only for the Consumer Rights Act sections.

## Out of scope

- src/alteram/law/legislation.py, src/alteram/law/models.py and every other file.
- Splitting text and building chunks, apart from what the fix requires.

## Acceptance criteria

1. New tests read tests/fixtures/law/legislation/ukpga-1974-39-section-88@*.xml through parse_document and merge_versions, and check: s.88(1), (4) and (5) from 2006-06-16 to open; s.88(2) and (3) from 2006-06-16 to 2006-10-01, then 2006-10-01 to open; s.88(4A) from 2008-10-01 to open.
2. The same s.88 spans come out when all the fixture files in that folder are merged together.
3. On 2026-11-01, every s.88 subsection has exactly one span in force.
4. Existing tests pass. Any test that asserted the old behaviour is changed and named in the commit message.
5. `uv run ruff check .`, `uv run ruff format --check src tests scripts` and `uv run pytest` pass.
