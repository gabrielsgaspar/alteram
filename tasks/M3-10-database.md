# Task: M3-10 local database, first real migration, and a database in CI

Mode: **local**, a supervised Claude Code session. It needs Docker and a running Postgres, and it changes `.github/workflows/ci.yml`, which the agent pipeline may not touch. Plan: `docs/milestones/M3.md`, step 10. Needs: step 09 merged. Decisions D8 and D9.

## Goal

Run Postgres 18 with pgvector locally through Docker Compose, apply the `law_chunks` migration to a real database for the first time, make the `db` tests from step 09 pass against it, and give CI the same database so those tests run on every PR.

## In scope

- `docker-compose.yml`: new. One service, `db`:
  - image `pgvector/pgvector:0.8.7-pg18-trixie`;
  - `127.0.0.1:5432:5432`;
  - `POSTGRES_USER=alteram`, `POSTGRES_DB=alteram`, `POSTGRES_HOST_AUTH_METHOD=trust` (so there is no password anywhere; the port is bound to localhost only);
  - a named volume mounted at `/var/lib/postgresql` (the PG 18 layout, see M3.md 4.1);
  - `./docker/initdb` mounted at `/docker-entrypoint-initdb.d`;
  - a `pg_isready` health check.
- `docker/initdb/01-test-database.sql`: new; `CREATE DATABASE alteram_test OWNER alteram;`.
- `.github/workflows/ci.yml`: add a `services.postgres` with the same image (pinned tag), trust auth, port 5432 and a health check. In the job env, set `ALTERAM_TEST_DATABASE_URL=postgresql://alteram@localhost:5432/alteram_test` and `ALTERAM_REQUIRE_DB=1`. A step creates `alteram_test` if the service image doesn't. Nothing else in CI changes; keep `permissions: contents: read` and the pinned actions.
- `README.md`: a short "Database" subsection: `docker compose up -d db`, `uv run alembic upgrade head`, and how to run `db` tests.
- Fixes in step 09's files (`migrations/`, `src/alteram/db.py`, `src/alteram/law/pg_store.py`, `tests/conftest.py`, `tests/test_pg_store.py`, `tests/test_law_store.py`) **only** where the real database shows a bug, each starting with the failing test output.
- `tasks/M3-10-database.md`: this file.

## Out of scope

- pg_textsearch or any custom image (decided in M4, D8).
- A backend container or running migrations from Compose (M2).
- Any other workflow file. Any change to how CI installs or caches.

## Gabriel runs

Claude Code's sandbox can't reach Docker or `localhost:5432`, so run these in your terminal and paste the output:

```bash
cd ~/projects/alteram
docker compose up -d db && docker compose ps
ALTERAM_DATABASE_URL=postgresql://alteram@localhost:5432/alteram uv run alembic upgrade head
docker compose exec db psql -U alteram -d alteram -c '\d law_chunks'
ALTERAM_TEST_DATABASE_URL=postgresql://alteram@localhost:5432/alteram_test ALTERAM_REQUIRE_DB=1 uv run pytest -m db -v
ALTERAM_DATABASE_URL=postgresql://alteram@localhost:5432/alteram uv run alembic downgrade base
ALTERAM_DATABASE_URL=postgresql://alteram@localhost:5432/alteram uv run alembic upgrade head
```

Because this step changes `.github/`, you review the CI diff before pushing. Then watch CI with `gh run watch`.

## Acceptance criteria

1. `docker compose ps` shows `db` healthy, and `\d law_chunks` matches M3.md 6.3 (columns, generated `search_tsv`, the four indexes, both CHECK constraints).
2. `alembic downgrade base` then `upgrade head` both succeed.
3. `uv run pytest -m db` passes against the local database with `ALTERAM_REQUIRE_DB=1`: every contract test in `tests/test_law_store.py` passes for both `memory` and `postgres`.
4. On the PR, the CI `test` job shows the `db` tests as passed, not skipped (quote the pytest summary line from the log).
5. Plain `uv run pytest` with no database variables still passes, with `db` tests skipped.
6. No password, token or key appears in any changed file.
7. `uv run ruff check .` and `uv run ruff format --check .` pass.
