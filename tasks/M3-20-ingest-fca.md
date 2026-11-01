# Task: M3-20 ingest CONC and DISP, and close M3

Mode: **local**, a supervised Claude Code session. Gabriel runs the paid commands in his own terminal. Plan: `docs/milestones/M3.md`, step 20. Needs: steps 17 and 19 merged; the FCA chapters saved by the route agreed in step 18.

## Goal

Add the FCA chapters chosen under D3 (CONC 1, 5, 6, 7 and DISP 1, 2, 3) to the law library, then record M3 as done, with measured costs and anything the next milestone should know.

## In scope

- `law/manifest.json`: updated with `fca-conc` and `fca-disp` entries.
- `docs/SETUP_LOG.md`: an "M3 done" entry with chunk counts per source, total measured cost, spot checks, known gaps (base date, unapplied effects, FCA point-in-time limits), and notes for M4 (pg_textsearch, `rerank-3`, `voyage-context-4` ablation).
- `docs/ALTERAM_V1_DESIGN.md`: only the corrections from `docs/milestones/M3.md` section 5 that Gabriel accepts in the session, each a minimal edit.
- Bug fixes found by real data, test first, as in step 17.
- `tasks/M3-20-ingest-fca.md`: this file.

## Out of scope

- Any FCA download by script.
- Prompt changes (their own task).
- M4 work.

## Gabriel runs

```bash
cd ~/projects/alteram && git pull && uv sync && docker compose up -d db
# place saved chapter files and law/raw/<source>/manifest.txt as described in issue 19
for s in fca-conc fca-disp; do uv run alteram law build $s && uv run alteram law ingest $s --dry-run; done
uv run alteram law ingest fca-conc --budget 5
uv run alteram law ingest fca-disp --budget 5
uv run alteram law status
uv run alteram law search "time limits for referring a complaint to the ombudsman" --keyword-only --as-of 2026-06-01
uv run alteram law show <the DISP 2.8.2R chunk ID>
```

## Acceptance criteria

1. `law status` shows every source `OK` with one embedding model.
2. The DISP search returns DISP 2.8 chunks first, with the attribution stored on each.
3. A rerun dry-run of both FCA sources reports 0 calls and $0.00.
4. The total measured M3 cost is in the setup log, and each paid run stayed under its $5 budget.
5. Every item of "Done when" in `docs/milestones/M3.md` section 2 is ticked in the setup-log entry, with the evidence for each.
6. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
