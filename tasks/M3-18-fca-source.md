# Task: M3-18 FCA Handbook: access route and fixtures

Mode: **local**, a supervised Claude Code session. Plan: `docs/milestones/M3.md`, steps 18–20 and sections 3.2 and 4.3. Needs: decision D2 answered (a or b; if c, FCA is deferred and this task is not run in M3) and D3 (chapters).

## Goal

Settle how FCA Handbook text may be obtained and stored under the FCA's terms, save a few sample rules in that form as fixtures, and complete issue 19 in `docs/milestones/M3-issues.md`, so the pipeline can build the FCA parser.

## In scope

- `docs/SETUP_LOG.md`: a dated decision recording the route, quoting the FCA's written answer if D2(a), or the terms relied on if D2(b), and the licence and attribution text to store with each FCA chunk.
- `tests/fixtures/law/fca/`: 3–5 hand-saved files covering at least DISP 2.8.2R, one CONC rule (R), one guidance paragraph (G), and one page with navigation or footer text to strip. Add `SOURCES.md` with the URL, date saved, how it was saved (browser "Save as", PDF export, …), the sha256, and the attribution.
- `docs/milestones/M3-issues.md`: complete issue 19. Replace each `[18]` marker with the file format, the patterns for rule numbers and status letters, where the in-force date appears, the strings to strip, and the chapters and attribution for `sources.toml`; then remove the note at its top.
- `pyproject.toml`, `uv.lock`: only if the saved format needs a parser library (e.g. `pypdf` for PDFs), and only after Gabriel approves that dependency in the session.
- `tasks/M3-18-fca-source.md`: this file.

## Out of scope

- Any script that downloads from fca.org.uk or handbook.fca.org.uk.
- The parser itself (issue 19).

## Gabriel does

- D2(a): email handbook.feedback@fca.org.uk asking for written consent to (1) download CONC, DISP and PRIN 2A by script or as PDFs and (2) store them in a private, non-public retrieval index for a non-commercial research project, with OGL attribution. Paste the answer into the session.
- Save the sample pages in a browser, as agreed, into `tests/fixtures/law/fca/`.

## Acceptance criteria

1. The setup-log decision names the route and quotes the terms or consent it relies on.
2. Every fixture file is listed in `SOURCES.md` with a matching sha256.
3. Issue 19 in `docs/milestones/M3-issues.md` has no `[18]` markers left, and every Done-when item can be checked against the fixtures.
4. No dependency was added without Gabriel's approval recorded in the session.
5. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
