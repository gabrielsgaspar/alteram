# Task: M3-17 ingest the Consumer Rights Act 2015, the Consumer Credit Act 1974 and the Limitation Act 1980

Mode: **local**, a supervised Claude Code session. Gabriel runs the network and paid commands in his own terminal, because the sandbox cannot read `.env` or reach legislation.gov.uk, Anthropic, Voyage or the database. Plan: `docs/milestones/M3.md`, step 17. Needs: steps 10 and 16 merged; `VOYAGE_API_KEY`, `ALTERAM_EMBEDDING_MODEL=voyage-4-large`, `ALTERAM_HEADER_MODEL=claude-haiku-5-5`, `ALTERAM_HTTP_CONTACT` and `ALTERAM_DATABASE_URL` set in `.env`.

## Goal

Fill the law library with every point-in-time version of the CRA 2015, CCA 1974 and Limitation Act 1980 sections in `law/sources.toml`, with headers and embeddings. Check the result by hand against legislation.gov.uk, and commit the manifest.

## In scope

- `law/manifest.json`: new, as written by `alteram law load`.
- `docs/SETUP_LOG.md`: a dated entry with the chunk counts, unapplied effects found, measured header and embedding cost, and the spot checks done.
- Bug fixes found by real data, each starting with a failing test built from a new small fixture (downloaded the same way as in step 01), in the file that has the bug.
- `tasks/M3-17-ingest-statutes.md`: this file.

## Out of scope

- FCA sources (steps 18 to 20).
- Prompt changes. If the five sample headers are poor, stop. A new prompt version is its own task through `prompt-change`.
- Re-embedding with another model or dimension.

## Gabriel runs

```bash
cd ~/projects/alteram && git pull && uv sync && docker compose up -d db
uv run alembic upgrade head
for s in cra-2015 cca-1974 limitation-1980; do uv run alteram law fetch $s && uv run alteram law build $s; done
uv run alteram law headers cra-2015 --limit 5          # about $0.01; read the five headers
uv run alteram law ingest cra-2015 --dry-run           # check calls and worst-case cost
uv run alteram law ingest cra-2015 --budget 5
uv run alteram law ingest cca-1974 --dry-run
uv run alteram law ingest cca-1974 --budget 5
uv run alteram law ingest limitation-1980 --dry-run
uv run alteram law ingest limitation-1980 --budget 5
uv run alteram law ingest cra-2015 --dry-run           # expect 0 header calls, 0 embeddings, $0.00
uv run alteram law status
uv run alteram law show ukpga/2015/15/section/9/1/2015-10-01
uv run alteram law search "contents and effect of default notice" --keyword-only --as-of 2006-09-01
uv run alteram law search "contents and effect of default notice" --keyword-only --as-of 2006-11-01
grep -c '"ukpga/1974/39/section/75' law/chunks/cca-1974.jsonl   # expect 0
```

(Words in CCA s.88(2) were substituted on 1 October 2006; see step 01's fixtures.) The `grep` checks that nothing from s.75 or s.75A was built (D4); it matches both. Paste the output into the session.

## Acceptance criteria

1. `law status` shows `cra-2015`, `cca-1974` and `limitation-1980`, each `OK`, with one embedding model.
2. The rerun dry-run reports 0 header calls, 0 embedding calls and $0.00.
3. The two `--as-of` searches return different `in_force_from` dates for s.88(2), and the `grep` prints 0.
4. `law show` for CRA s.9(1) prints the exact text "Every contract to supply goods is to be treated as including a term that the quality of the goods is satisfactory." under Original text, with a separate header.
5. Five chunks, chosen by Gabriel, match their legislation.gov.uk pages word for word (listed in the setup-log entry), and the "Changes to legislation" box for CRA ss.9–24 and CCA ss.87–88 agrees with the manifest's unapplied effects. CCA s.87(6) (S.I. 2025/859, in force in part from 15 July 2025 and in full from 15 July 2026) has the spans the page shows.
6. Measured paid cost is in the setup log and under $5.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
