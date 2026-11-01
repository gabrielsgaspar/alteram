# Task: M3-01 foundations for the law library

Mode: **local**, a supervised Claude Code session in `~/projects/alteram`. It is not for `build_review.py` or `ship.py`, because it changes `pyproject.toml`, `uv.lock` and `AGENTS.md`, and needs files from legislation.gov.uk. Plan: `docs/milestones/M3.md`, step 01. Needs: nothing more. Gabriel answered D1–D9 and approved the three dependencies on 1 November 2026 (section 10).

## Goal

Make every later M3 step possible without touching protected files. Add the approved dependencies, the new environment variable names and ignore rules, the legislation.gov.uk fixture files the pipeline tests read, and Gabriel's M3 decisions in the setup log.

## In scope

- `pyproject.toml`, `uv.lock`: add `alembic>=1.20`, `psycopg[binary]>=3.3` and `httpx` (version range matching what `uv.lock` already resolves through `anthropic`) with `uv add`. Nothing else changes.
- `.env.example`: add, with empty values, `ALTERAM_DATABASE_URL`, `ALTERAM_TEST_DATABASE_URL`, `ALTERAM_REQUIRE_DB`, `VOYAGE_API_KEY`, `ALTERAM_EMBEDDING_MODEL`, `ALTERAM_HEADER_MODEL`, `ALTERAM_HTTP_CONTACT`.
- `AGENTS.md`: the same seven names in the Secrets table, with the purposes in `docs/milestones/M3.md` section 6.7. No other change.
- `.gitignore`: `law/raw/`, `law/chunks/`, `law/cache/`.
- `tests/fixtures/law/legislation/`: the XML files below, downloaded by Gabriel, plus `SOURCES.md` listing for each file its URL, the date fetched, its sha256 and its purpose, and the attribution "© Crown and database right. Derived from content available under the Open Government Licence v3.0 from legislation.gov.uk."
  - `ukpga-2015-15-section-9@2015-10-01.xml`: plain subsections (`/ukpga/2015/15/section/9/2015-10-01/data.xml`).
  - `ukpga-2015-15-section-22@2015-10-01.xml`: a long section with many subsections.
  - `ukpga-2015-15-section-12@current.xml`: carries the unapplied Digital Markets, Competition and Consumers Act 2024 effect (`/ukpga/2015/15/section/12/data.xml`).
  - `ukpga-1974-39-section-88@current.xml`: has the `hasVersion` list (on 1 Nov 2026: 1991-02-01, 2006-06-16, 2006-10-01, 2008-10-01).
  - `ukpga-1974-39-section-88@2006-06-16.xml`, `@2006-10-01.xml`, `@2008-10-01.xml`: three **adjacent** dated versions. Words in s.88(2) and (3) were substituted on 1 Oct 2006 and s.88(4A) was inserted on 1 Oct 2008, so both "changed text" and "new subsection" are covered. Record this in `SOURCES.md`. (CCA s.75 is no longer in the library, D4.)
  - `ukpga-1974-39-section-140A@1990-01-01.xml`: the base-date case, with `Match="false"` parts.
  - Total under 1 MB. If any file is larger than 300 KB, say so before committing.
- `docs/SETUP_LOG.md`: under Decisions, one dated line (1 November 2026) per decision D1–D9 as in `docs/milestones/M3.md` section 10, including the reason for leaving out CCA ss.75 and 75A (D4) and the D2 fallback, and a line recording the old local branch `plan/M3-2026-10-30` as superseded by `docs/milestones/M3.md`. Also a line saying `www.legislation.gov.uk` stays out of `.claude/settings.json` because the GitHub agent workflows load project settings too.
- `tasks/M3-01-foundations.md`: this file.

## Out of scope

- Any code under `src/` or `tests/` other than the fixture directory.
- `.github/`, `.claude/`, `prompts/`, `cases/`, `.env`.
- Creating `law/sources.toml` (step 12) or any directory under `law/` other than through `.gitignore`.

## Gabriel runs

The sandbox cannot reach legislation.gov.uk, and `www.legislation.gov.uk` is deliberately not in `.claude/settings.json` (the GitHub agent workflows load project settings too). Run all of these in your own terminal before the session, then start the session:

```bash
cd ~/projects/alteram
d=tests/fixtures/law/legislation && mkdir -p $d
u=https://www.legislation.gov.uk
ua="alteram-fixtures (+https://github.com/gabrielsgaspar/alteram)"
curl -fsSL -A "$ua" $u/ukpga/2015/15/section/9/2015-10-01/data.xml  -o $d/ukpga-2015-15-section-9@2015-10-01.xml
curl -fsSL -A "$ua" $u/ukpga/2015/15/section/22/2015-10-01/data.xml -o $d/ukpga-2015-15-section-22@2015-10-01.xml
curl -fsSL -A "$ua" $u/ukpga/2015/15/section/12/data.xml            -o $d/ukpga-2015-15-section-12@current.xml
curl -fsSL -A "$ua" $u/ukpga/1974/39/section/88/data.xml            -o $d/ukpga-1974-39-section-88@current.xml
curl -fsSL -A "$ua" $u/ukpga/1974/39/section/88/2006-06-16/data.xml -o $d/ukpga-1974-39-section-88@2006-06-16.xml
curl -fsSL -A "$ua" $u/ukpga/1974/39/section/88/2006-10-01/data.xml -o $d/ukpga-1974-39-section-88@2006-10-01.xml
curl -fsSL -A "$ua" $u/ukpga/1974/39/section/88/2008-10-01/data.xml -o $d/ukpga-1974-39-section-88@2008-10-01.xml
curl -fsSL -A "$ua" $u/ukpga/1974/39/section/140A/1990-01-01/data.xml -o $d/ukpga-1974-39-section-140A@1990-01-01.xml
date -u +%F > $d/.fetched-on && sha256sum $d/*.xml
```

That is 8 requests, far under the fair-use limit. Paste the `sha256sum` output into the session; Claude writes `SOURCES.md` from it and checks the s.88 `hasVersion` list. If that list no longer matches the dates above, Claude gives you replacement `curl` lines for three adjacent versions.

## Acceptance criteria

1. `uv sync --locked` succeeds, and `git diff main -- pyproject.toml` shows only the three new dependencies.
2. `.env.example` and the `AGENTS.md` table each contain exactly the seven new names, and `.env.example` has no value after any `=`.
3. `git check-ignore law/raw/x law/chunks/x law/cache/x` prints all three paths.
4. Every fixture is well-formed XML (`python -c "import xml.etree.ElementTree as E,sys; [E.parse(f) for f in sys.argv[1:]]" tests/fixtures/law/legislation/*.xml`), and every sha256 in `SOURCES.md` matches `sha256sum`.
5. The three dated s.88 versions are adjacent in the `hasVersion` list of `@current.xml`, and the text differs between each pair (the `diff` is shown in the report).
6. `docs/SETUP_LOG.md` has the D1–D9 lines and the settings line.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with the same test count as `main`.
