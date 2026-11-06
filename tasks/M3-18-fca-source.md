# Task: M3-18 FCA Handbook: access route and fixtures

Mode: **local**, a supervised Claude Code session. Plan: `docs/milestones/M3.md`, steps 18–20 and sections 3.2 and 4.3. Needs: the FCA's written consent, asked for under D2(a). If there is no answer by step 17, FCA is deferred (D2(c)) and this task is not run in M3. Chapters: D3 (CONC 1, 5, 6, 7; DISP 1, 2, 3; no PRIN 2A).

## Goal

Settle how FCA Handbook text may be obtained and stored under the FCA's terms, save a few sample rules in that form as fixtures, and complete issue 19 in `docs/milestones/M3-issues.md`, so the pipeline can build the FCA parser.

## In scope

- `docs/SETUP_LOG.md`: a dated decision recording the route, quoting the FCA's written answer and any conditions in it, and the licence and attribution text to store with each FCA chunk.
- `scripts/fca_save.py`: saves Handbook section pages, or every live section of a chapter (`--list` to only print them), with a headless browser (Playwright, run with `uv run --with playwright`; not a project dependency). One page at a time, at least 3 seconds apart (`--delay`), with `ALTERAM_HTTP_CONTACT` in the User-Agent. Writes the rendered HTML (the format chosen for the parser on 2026-11-05), a JSON sidecar per page, and `report.json` per output folder. Skips and reports sections that are not found or render empty; stops on a CAPTCHA, a 403 or a 429.
- `tests/test_fca_save.py`: unit tests for the script's pure parts (paths and file names, link and data filtering, the sidecar, the report, pacing), with no browser or network.
- `law/raw/fca-conc/`, `law/raw/fca-disp/`: CONC 1, 5, 6, 7 and DISP 1, 2, 3, to be downloaded with `scripts/fca_save.py` for step 20, each with `report.json`. Gitignored; never committed. On 2026-11-05 the site refused the download (HTTP 429) twice, so no section is saved yet; each `report.json` lists the missing sections for step 20.
- `tests/fixtures/law/fca/`: DISP 2.8, CONC 7.3 and CONC 5.2A saved by `scripts/fca_save.py` (HTML and sidecar each), covering at least DISP 2.8.2R, one CONC rule (R), one guidance paragraph (G), and one page with navigation or footer text to strip. Add `SOURCES.md` with the URL, date saved, how it was saved (`scripts/fca_save.py`, rendered HTML), the sha256, and the attribution.
- `docs/milestones/M3-issues.md`: complete issue 19. Replace each `[18]` marker with the file format, the patterns for rule numbers and status letters, where the in-force date appears, the strings to strip, and the chapters and attribution for `sources.toml`; then remove the note at its top.
- `pyproject.toml`, `uv.lock`: only if the saved format needs a parser library (e.g. `pypdf` for PDFs), and only after Gabriel approves that dependency in the session.
- `tasks/M3-18-fca-source.md`: this file.

## Out of scope

- The parser itself (issue 19).

## Gabriel does

- D2(a): email handbook.feedback@fca.org.uk asking for written consent to (1) download CONC 1, 5, 6, 7 and DISP 1, 2, 3 by script or as PDFs and (2) store them in a private, non-public retrieval index for a non-commercial research project, with OGL attribution. Paste the answer into the session.
- Provide the FCA's written consent for the setup log. Gabriel has stated it was received and covers automated download and private storage; the email's wording is quoted when he pastes it.
- Install Chromium once (`uv run --with playwright playwright install --with-deps chromium`) and choose the format for the parser. On 2026-11-05 Gabriel asked Claude Code to run `scripts/fca_save.py` itself (sandboxed, with the two Handbook hosts allowed per command) for the fixtures and the full chapters.

## Acceptance criteria

1. The setup-log decision names the route and quotes the terms or consent it relies on.
2. Every fixture file is listed in `SOURCES.md` with a matching sha256.
3. Issue 19 in `docs/milestones/M3-issues.md` has no `[18]` markers left, and every Done-when item can be checked against the fixtures.
4. No dependency was added without Gabriel's approval recorded in the session.
5. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
