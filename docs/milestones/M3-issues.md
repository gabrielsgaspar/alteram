# M3 pipeline issues

GitHub issue bodies for the pipeline steps in `docs/milestones/M3.md`, ready to paste into the **Agent task** template. Each has a title line, a "Needs" line (don't add `agent-build` until those steps are merged on `main`), then Goal, In scope, Out of scope and Done when.

Shared rules for all of them, stated once here and repeated briefly in each issue:

- Conventions live in `docs/milestones/M3.md` section 6. Read it before planning.
- Tests never call a model or the network, and never need Docker or a database. Use fakes, `httpx.MockTransport` and the committed fixtures.
- No new dependencies. `pyproject.toml`, `uv.lock`, `.env.example`, `.github/`, `.claude/`, `prompts/` and `cases/` are out of scope unless an issue names them.
- Type hints everywhere; small functions; every function with logic gets a test.

Issue 19 is completed in step 18 once the FCA file format is known.

---

## Issue 03

**Title:** `Task: M3-03 law data models, library IDs and validity`

**Needs:** nothing (this plan merged).

```markdown
## Goal

Add the typed data models the M3 law library is built on, so later steps (parser, chunker, store, loader) share one definition of a provision, a chunk, a library ID and "in force on a date". Conventions: docs/milestones/M3.md sections 6.1 to 6.4.

## In scope

- `src/alteram/law/__init__.py`: new, empty package marker (a docstring is fine).
- `src/alteram/law/models.py`: new. Pydantic v2 models and pure functions:
  - `DocType` and `AuthorityTier` literals: `statute`, `regulation`, `decision`, `case_law`, `guidance`.
  - `Provision`: `source`, `uri_path` (e.g. `ukpga/2015/15/section/9/1`), `heading_path: list[str]`, `number` (e.g. `9(1)`), `text`, `extent: str | None`, `in_force_from: date`, `in_force_to: date | None`, `status` (`in_force`, `prospective`, `repealed`), `unapplied_effects: list[str]`, `authority_tier: AuthorityTier | None = None` (overrides the source's tier when set; FCA guidance uses it).
  - `LawChunk`: every column of the `law_chunks` table in M3.md 6.3 except `embedding`, `embedding_model`, `ingested_at` and `search_tsv`. Validators: `in_force_to` is after `in_force_from` when set; the date in `id` equals `in_force_from`; `chunk_sha256` matches `chunk_sha256(heading_path, text_original)`.
  - `StoredChunk(LawChunk)`: adds `embedding_model: str | None` and `ingested_at: datetime | None`.
  - `SearchFilters`: optional `doc_types`, `jurisdictions`, `sources`, `topics` (all `frozenset[str] | None`); it has no field that could include holdout rows.
  - `SearchHit`: `chunk_id`, `score: float`, `rank: int` (from 1), `backend` (`memory`, `postgres_fts`, `pgvector`).
  - `library_id(uri_path, in_force_from, part=None) -> str` and `parse_library_id(id) -> (uri_path, in_force_from, part)`, per M3.md 6.2, including the `~<n>` suffix for split parts and the `fca/<SOURCEBOOK>/<rule>/<date>` form.
  - `in_force_on(chunk_or_provision, as_of) -> bool`, using the half-open rule in M3.md 6.2.
  - `jurisdiction_from_extent(extent) -> str`: `E+W+S+N.I.` → `uk`, `E+W` → `england_wales`, `E+W+S` → `great_britain`, None → `unknown`; anything else raises `ValueError`.
  - `chunk_sha256(heading_path, text) -> str`: sha256 hex of the heading path joined by `\n`, then `\n\n`, then the text, UTF-8.
- `tests/test_law_models.py`: new.

## Out of scope

- Any other file. In particular `src/alteram/models.py` (agent models stay there; law data models go here, per M3.md 6.1), `pyproject.toml`, `uv.lock`.
- Parsing, storage, embeddings or any I/O.

## Done when

1. `library_id("ukpga/2015/15/section/9/1", date(2015,10,1))` is `ukpga/2015/15/section/9/1/2015-10-01`; with `part=2` it ends in `2015-10-01~2`; `parse_library_id` round-trips both and an FCA ID such as `fca/DISP/2.8.2R/2025-01-01`. A malformed ID raises `ValueError` (tested with at least three bad forms).
2. `in_force_on` is tested on the start date (true), the day before (false), the `in_force_to` date (false), the day before it (true) and an open-ended span (true far in the future).
3. `LawChunk` rejects: `in_force_to` equal to `in_force_from`; an ID whose date differs from `in_force_from`; a wrong `chunk_sha256`. Each has a test.
4. `jurisdiction_from_extent` has a parametrised test covering every mapping above and one unknown value.
5. `SearchFilters` has no field mentioning holdout (a test asserts this on `model_fields`).
6. `git diff --stat main` lists only the three files in scope.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 04

**Title:** `Task: M3-04 parse legislation.gov.uk XML (CLML) into provisions`

**Needs:** 01 (fixtures in `tests/fixtures/law/legislation/`), 03.

```markdown
## Goal

Turn one legislation.gov.uk XML document (CLML, `/data.xml`) into a list of `Provision`s with clean text, heading path, extent, validity dates, status and the unapplied effects that affect each one, so the chunker never sees XML. Facts about the format: docs/milestones/M3.md section 4.2.

## In scope

- `src/alteram/law/legislation.py`: new. Standard library only (`xml.etree.ElementTree`).
  - `parse_document(xml: bytes, source: str) -> ParsedDocument` where `ParsedDocument` (a Pydantic model in this file) has `uri_path` of the document, `valid_from` (`dct:valid`), `restrict_start`/`restrict_end` from the root, `version_dates: list[date]` from the `atom:link rel="http://purl.org/dc/terms/hasVersion"` links (dated titles only; skip `enacted`, `prospective`, `current`), and `provisions: list[Provision]`.
  - One `Provision` per subsection (`P2`); a section (`P1`) with no subsections is one provision. `P3` and deeper stay inside their subsection's text, each on its own line, with its number, e.g. `(a) ...`.
  - `heading_path`: Act title, then Part, Chapter and cross-heading titles where present, then `s.<n> <section title>`.
  - Text: `Pnumber`s and `Text` with every `CommentaryRef` removed, `Addition`/`Substitution` wrappers unwrapped (their text kept), and `Commentaries`, `Footnotes` and editorial notes dropped. Whitespace normalised; no XML left.
  - Validity per provision from the nearest `RestrictStartDate`/`RestrictEndDate` on the provision or its ancestors, falling back to the document's. The tests must pin down, from the two adjacent CCA s.75 fixtures, whether `RestrictEndDate` is inclusive, and convert to the exclusive `in_force_to` of M3.md 6.2.
  - `status`: `prospective` or `repealed` from `Status`; provisions with `Match="false"` are returned with `status="prospective"` if prospective, otherwise left out and counted in `ParsedDocument.skipped`.
  - `unapplied_effects`: the `ukm:UnappliedEffect` entries whose `AffectedProvisions` cover this provision (not the whole Act's list), as short strings.
- `tests/test_legislation.py`: new, using the files listed in `tests/fixtures/law/legislation/SOURCES.md`.

## Out of scope

- Fetching (step 12), merging versions (step 05), chunk IDs or splitting (step 05).
- The fixture files themselves: read them, do not edit or add any.
- `pyproject.toml`, `uv.lock`; no `lxml` or other new dependency.

## Done when

1. For CRA s.9 at 2015-10-01, the parser returns one provision per subsection; s.9(1)'s text is exactly "Every contract to supply goods is to be treated as including a term that the quality of the goods is satisfactory." and its heading path starts with "Consumer Rights Act 2015" and ends with the s.9 title.
2. No provision text from any fixture contains `<`, `>`, an F-note marker such as `F1`, or text from a `Commentary` element (a test checks each fixture).
3. `version_dates` for the current CCA s.75 fixture matches the dated `hasVersion` links in it, in ascending order.
4. For the two adjacent CCA s.75 fixtures, the earlier version's `in_force_to` equals the later version's `in_force_from`, and a test documents whether `RestrictEndDate` was inclusive.
5. The CRA s.12 fixture yields at least one provision with a non-empty `unapplied_effects`, and the CCA s.75 fixture's provisions do not list effects aimed only at other sections.
6. The CCA s.140A fixture requested at 1990-01-01 reports `valid_from` 1991-02-01 and counts its `Match="false"` parts in `skipped` (or marks them prospective), as the test documents.
7. `git diff --stat main` lists only the two files in scope.
8. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 05

**Title:** `Task: M3-05 merge point-in-time versions into spans and build chunks`

**Needs:** 03.

```markdown
## Goal

Given the provisions parsed from several dated versions of the same document, produce one chunk per distinct text per validity span, with library IDs, so the library stores each version of a provision once with correct `in_force_from` and `in_force_to`. Conventions: docs/milestones/M3.md sections 6.2 and 6.5 (build).

## In scope

- `src/alteram/law/chunk.py`: new.
  - `merge_versions(provisions: Iterable[Provision]) -> list[Provision]`: groups by `uri_path`; within a group, sorts by `in_force_from`; joins consecutive versions with identical text into one span; a change of text starts a new span; a provision missing from a later version, or `repealed`, ends its span at that version's date; `prospective` provisions are dropped. Explicit `in_force_to` values from the parser win over inferred ones. Overlapping spans with different text raise `ValueError` naming the `uri_path`.
  - `split_text(text, limit=4000) -> list[str]`: splits only at line or paragraph boundaries; a single line over the limit is split at the last sentence end before it, else hard-split; parts after the first start with the heading's last element in brackets, e.g. `[s.22 Time limit for short-term right to reject]`.
  - `to_chunks(provisions, source_meta) -> list[LawChunk]`, where `source_meta` is a small model in this file with `source`, `source_url_base`, `doc_type`, `authority_tier`, `licence`, `attribution`, `topics_by_section: dict[str, list[str]]`. IDs from `library_id()`; `part` set only when split (1-based); `authority_tier` from the provision when set, else from `source_meta`; jurisdiction from `jurisdiction_from_extent()`; `source_url` is `https://www.legislation.gov.uk/<uri_path>/<in_force_from>`; `source_sha256` is passed in per provision; topics from the section number.
- `tests/test_chunk.py`: new. Build provisions directly in the tests; no XML.

## Out of scope

- XML parsing (step 04), file I/O and JSONL (step 13), headers and embeddings.
- `src/alteram/law/models.py`: use it, don't change it. If a change looks needed, say so in the plan instead.

## Done when

1. Three versions of one provision where versions 1 and 2 have identical text and version 3 differs give exactly two spans, the first ending on version 3's start date and the second open-ended.
2. A provision present in versions 1 and 2 and absent from version 3 ends on version 3's date; a `repealed` version ends the span the same way.
3. Overlapping spans with different text raise `ValueError` naming the provision.
4. `split_text` never returns a part over the limit, never splits inside a line when a line boundary exists, and the parts after the first start with the bracketed heading (tests for each).
5. `to_chunks` gives IDs that `parse_library_id` round-trips, and split parts get `~1`, `~2`, …; an unsplit provision has no suffix.
6. Output order is deterministic: the same input in shuffled order gives the same list (tested).
7. `git diff --stat main` lists only the two files in scope.
8. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 06

**Title:** `Task: M3-06 LawStore protocol, MemoryStore and contract tests`

**Needs:** 03.

```markdown
## Goal

Define the storage interface the law library and M4's retrieval are written against (design section 9.2), with an in-memory implementation used as the fake in every later test, and contract tests that a Postgres store will have to pass too.

## In scope

- `src/alteram/law/store.py`: new. The `LawStore` protocol exactly as in docs/milestones/M3.md section 6.4, plus `cosine(a, b)` and `normalise_query(text)` helpers if useful.
- `src/alteram/law/memory_store.py`: new. `MemoryStore(LawStore)` with `backend = "memory"`.
  - `search_vector`: cosine similarity in plain Python (no numpy); only chunks with an embedding.
  - `search_keyword`: lower-cased word overlap between query and `text_contextual or text_original`, ignoring a small fixed stop-word list; ties broken by chunk ID; zero-score chunks not returned.
  - Both apply, before ranking: `in_force_on(chunk, as_of)`, `holdout is False`, and every non-None `SearchFilters` field. Hits carry `rank` from 1, `score` and `backend` (`memory`).
  - `upsert` replaces by ID; a chunk upserted without an embedding keeps none; `embedding_model` must be given if any embedding is.
- `tests/test_law_store.py`: new. Contract tests written against a `store` fixture parametrised over implementations (only `MemoryStore` for now), so step 09 can add Postgres by extending the fixture's params.

## Out of scope

- Postgres, SQL, embeddings from a real model, fusion or reranking (M4).
- `src/alteram/law/models.py`: use it, don't change it.

## Done when

1. Contract tests cover: `as_of` before, on and after a span boundary; holdout chunks never returned by either search but returned by `get`; each `SearchFilters` field; `k` respected; ranks start at 1 and are contiguous; `remove` and `ids`; `counts` and `embedding_models`.
2. Upserting the same chunk twice leaves one row; upserting with embeddings but no `embedding_model` raises `ValueError`.
3. All contract tests take the store from one parametrised fixture, and the test module has no `MemoryStore`-specific assertions outside a clearly separated section.
4. `git diff --stat main` lists only the three files in scope.
5. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 07

**Title:** `Task: M3-07 embedder interface, Voyage client over httpx, fake, and prices`

**Needs:** 01 (`httpx` declared as a dependency).

```markdown
## Goal

Give the law library one embedding interface with a real Voyage implementation and a deterministic fake, and add the prices for Claude Haiku 5.5 and Voyage embeddings, so ingestion can be costed and tested without network. Facts: docs/milestones/M3.md section 4.4.

## In scope

- `src/alteram/law/embed.py`: new.
  - `Embedded` (Pydantic): `vectors: list[list[float]]`, `total_tokens: int`.
  - `Embedder` protocol: `model: str`, `dimension: int`, `embed_documents(texts) -> Embedded`, `embed_query(text) -> Embedded`.
  - `VoyageEmbedder(model, dimension=1024, api_key=None, client: httpx.Client | None = None)`: `POST https://api.voyageai.com/v1/embeddings` with `input`, `model`, `input_type` (`document` or `query`), `output_dimension`; key from the argument or `VOYAGE_API_KEY` (read with `os.environ`, never logged); batches of at most 128 texts and an estimated 100,000 tokens (4 characters per token); results reordered by `data[].index`; retries 429 and 5xx up to 4 times with exponential backoff through an injectable `sleep`; raises if any vector's length differs from `dimension`.
  - `FakeEmbedder(dimension=1024)`: hashes each lower-cased word into a bucket, sums, L2-normalises; same text → same vector; texts that share words have higher cosine than texts that don't. `total_tokens` = word count.
- `tests/test_embed.py`: new. `VoyageEmbedder` tested only through `httpx.MockTransport`.
- `src/alteram/pricing.py`: add `"claude-haiku-5-5": Price(0.10, 0.50)` to `PRICES` with a comment that it is the up-to-100,000-token rate; add `EMBEDDING_PRICES: dict[str, float]` (USD per million tokens) with `"voyage-4-large": 0.12`, `EMBEDDING_PRICES_URL = "https://docs.voyageai.com/docs/pricing"`, `EMBEDDING_PRICES_CHECKED = "2026-11-01"`, and `embedding_cost_usd(model, tokens)` raising `UnknownModel` for a missing row. Update `PRICES_CHECKED` to `"2026-11-01"`.
- `tests/test_pricing.py`: tests for the new row, table and function.

## Out of scope

- Any real network call, in tests or otherwise; the `voyageai` package; `pyproject.toml`, `uv.lock`, `.env.example`.
- Changing existing prices or `Budget` behaviour.

## Done when

1. A MockTransport test checks the request body (model, `input_type`, `output_dimension`), the `Authorization: Bearer` header, and that results come back in input order when the mock returns them shuffled by `index`.
2. 300 texts are sent as at least three requests, none over 128 texts.
3. Two 429 responses then a 200 succeed with two calls to the injected `sleep`; five 500s raise an error that does not contain the API key.
4. A response with a wrong vector length raises.
5. `FakeEmbedder` tests: determinism, unit length, and cosine("satisfactory quality goods", "goods of satisfactory quality") > cosine("satisfactory quality goods", "limitation period expired").
6. `embedding_cost_usd("voyage-4-large", 1_000_000) == 0.12`; an unknown model raises `UnknownModel`; `cost_usd("claude-haiku-5-5", 1_000_000, 1_000_000) == 0.60`.
7. No test touches the network (the suite passes with networking off) and no test reads `VOYAGE_API_KEY` from the real environment.
8. `git diff --stat main` lists only the four files in scope.
9. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 08

**Title:** `Task: M3-08 law library manifest`

**Needs:** 03.

```markdown
## Goal

Record what is in the law library, where it came from and which models produced it, in `law/manifest.json`, so a rerun or a model change can be checked in code (design section 6.6, step 5).

## In scope

- `src/alteram/law/manifest.py`: new.
  - `SourceEntry` (Pydantic): `source`, `title`, `licence`, `attribution`, `raw_files: dict[str, str]` (URL → sha256), `version_dates: list[date]`, `chunk_count`, `unapplied_effects: dict[str, list[str]]` (provision URI path → effects), `header_model: str | None`, `header_prompt_version: int | None`, `embedding_model: str | None`, `embedding_dimension: int | None`, `built_at: datetime`, `notes: list[str]`.
  - `Manifest`: `version: int = 1`, `sources: dict[str, SourceEntry]`.
  - `read_manifest(path) -> Manifest` (missing file → empty manifest); `write_manifest(path, manifest)`: JSON, two-space indent, keys sorted, trailing newline, dates as ISO strings, so the same manifest always gives the same bytes.
  - `check_embedding(manifest, model, dimension)`: raises `EmbeddingMismatch` naming every source whose model or dimension differs; passes on an empty manifest or sources without embeddings.
  - `update_source(manifest, entry) -> Manifest`: returns a new manifest with that source replaced.
- `tests/test_manifest.py`: new, using `tmp_path`.

## Out of scope

- Creating `law/manifest.json` itself (step 17 commits the real one).
- Any other file.

## Done when

1. Write then read round-trips a manifest with two sources, and writing it twice gives byte-identical files.
2. `check_embedding` passes for a matching model and dimension and raises `EmbeddingMismatch` naming the source for each kind of mismatch.
3. Reading a missing path gives an empty manifest; reading malformed JSON raises a clear error naming the path.
4. `git diff --stat main` lists only the two files in scope.
5. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 09

**Title:** `Task: M3-09 law_chunks migration, database module and PostgresStore`

**Needs:** 01 (`alembic`, `psycopg[binary]` declared), 06.

```markdown
## Goal

Write the Postgres side of the law store: the Alembic migration for `law_chunks`, a tiny database module, and `PostgresStore` implementing `LawStore`, with the SQL built in pure functions so it can be tested without a database. Real-database tests are written now, skip here, and are first run in step 10. Conventions: docs/milestones/M3.md sections 6.3, 6.4 and 7.

## In scope

- `alembic.ini`: new; `script_location = migrations`; no URL in the file.
- `migrations/env.py`: new; URL from `alteram.db.database_url()`; supports offline mode (`--sql`).
- `migrations/script.py.mako`: new; the standard template.
- `migrations/versions/0001_law_chunks.py`: new; `revision = "0001"`; `upgrade()` runs the SQL in M3.md 6.3 with `op.execute` (including `CREATE EXTENSION IF NOT EXISTS vector`); `downgrade()` drops the table (not the extension).
- `src/alteram/db.py`: new. `database_url() -> str` reads `ALTERAM_DATABASE_URL`, raises a clear error naming the variable when unset; `test_database_url() -> str | None` reads `ALTERAM_TEST_DATABASE_URL` and raises if the database name does not end in `_test`; `connect(url) -> psycopg.Connection`.
- `src/alteram/law/pg_store.py`: new. `PostgresStore(conn)` with `backend = "postgres"`. SQL comes from pure functions, e.g. `vector_search_sql(filters) -> (sql, params)` and `keyword_search_sql(filters) -> (sql, params)`, which always include the `as_of` validity condition and `holdout = false` in `WHERE`. Keyword search uses `websearch_to_tsquery('english', %(q)s)` and `ts_rank_cd` on `search_tsv`. Vector search uses `embedding <=> %(v)s::vector` and score `1 - distance`. Vectors are passed as text literals (`'[0.1,...]'`). Hits get `backend` `postgres_fts` or `pgvector`.
- `tests/conftest.py`: register a `db` marker in `pytest_configure`; add a `pg_conn` fixture that skips with "no test database" when `test_database_url()` is None, unless `ALTERAM_REQUIRE_DB=1`, in which case it fails; runs `alembic upgrade head` once per session and truncates `law_chunks` before each test. Keep everything already in this file unchanged.
- `tests/test_law_store.py`: add a `postgres` param to the store fixture, marked `db`, using `pg_conn`. Don't change existing tests.
- `tests/test_pg_store.py`: new; tests of the SQL builder functions as strings and params, and `db`-marked tests of SQL behaviour specific to Postgres (generated `search_tsv`, the CHECK constraints).
- `tests/test_migrations.py`: new; runs Alembic in offline mode against a dummy `postgresql+psycopg://u@localhost/x_test` URL (no connection is made) and checks the emitted SQL.

## Out of scope

- `docker-compose.yml`, any Docker file, `.github/` (step 10 adds the CI database).
- `pyproject.toml`, `uv.lock`, `.env.example`, `AGENTS.md` (step 01 already did these).
- The `pgvector` Python package or SQLAlchemy ORM models; fusion or reranking.

## Done when

1. `tests/test_migrations.py` passes and asserts the offline SQL contains `CREATE EXTENSION IF NOT EXISTS vector`, `CREATE TABLE law_chunks`, `USING hnsw (embedding vector_cosine_ops)`, `USING gin (search_tsv)` and both CHECK constraints.
2. Tests of `vector_search_sql` and `keyword_search_sql` show the validity condition and `holdout = false` are present for every combination of `SearchFilters` fields, and that filter values go into params, never into the SQL string.
3. `database_url()` raises an error naming `ALTERAM_DATABASE_URL` when it is unset; `test_database_url()` rejects a database named `alteram` (tests use `monkeypatch`).
4. With no test database set, `uv run pytest` reports the `db` tests as skipped with "no test database"; with `ALTERAM_REQUIRE_DB=1` and none set, the `pg_conn` fixture fails (tested with `pytester` or a direct fixture call).
5. The contract tests in `tests/test_law_store.py` are unchanged except for the added `postgres` param.
6. `git diff --stat main` lists only the files in scope.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 11

**Title:** `Task: M3-11 contextual header writer with cache and budget`

**Needs:** 02 (`prompts/contextual_header.md`), 03, 07 (Haiku price).

```markdown
## Goal

Write the contextual header step of the law library (design section 6.3): for each chunk, a short model-written header that places it in its document, cached so reruns are free and costed so a budget can stop it. Conventions: docs/milestones/M3.md section 6.5 (headers).

## In scope

- `src/alteram/models.py`: add `ContextualHeader` (Pydantic): `header: str`. Nothing else in this file changes.
- `src/alteram/law/contextual.py`: new.
  - Loads `prompts/contextual_header.md` by file name, reads its `version: N`, and computes its sha256 the same way the existing prompt loader does (reuse it if one exists).
  - `document_context(chunks, as_of, limit_chars=180_000) -> str`: the `text_original` of the given source's chunks in force on `as_of`, in ID order, under their heading paths; raises `ValueError` if over the limit.
  - `HeaderWriter(model: BaseChatModel, model_id: str, cache_path: Path, budget: Budget)`: `write(chunk, document) -> str`. The cache key is sha256 of model ID + prompt sha256 + document sha256 + chunk sha256. On a hit there is no model call. On a miss it estimates worst-case cost with `pricing.worst_case_usd` and asks the budget before calling. The document goes in its own content block marked for prompt caching (check current LangChain Anthropic docs for the syntax; with the fake model it is just passed through). It parses `ContextualHeader` and checks in code: non-empty, at most 600 characters, and not containing any 80-character run of the chunk text. One retry with the failed check named; then raise `HeaderCheckFailed`. Appends hits to the JSONL cache.
  - `contextual_text(header, original) -> str`: header, blank line, original.
- `tests/test_contextual.py`: new; uses LangChain's `GenericFakeChatModel` (as `tests/test_graph.py` does); no network.

## Out of scope

- `prompts/` (step 02 owns the prompt; read it, don't change it).
- Embeddings, storage and CLI (steps 14 and 15).
- Any real model call.

## Done when

1. A second `write` with the same inputs makes no model call (the fake records calls) and returns the same header; changing the prompt version, model ID, document or chunk causes a miss.
2. A header that is empty, longer than 600 characters, or copies 80 characters of the chunk is retried once with the reason, then `HeaderCheckFailed` is raised; each case is tested.
3. `document_context` over the limit raises; in-force filtering uses `in_force_on` (tested with two spans).
4. A budget too small for one call raises `BudgetExceeded` before any model call.
5. `ContextualHeader` is the only change to `src/alteram/models.py`.
6. `git diff --stat main` lists only the three files in scope.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 12

**Title:** `Task: M3-12 law sources file and polite legislation.gov.uk fetcher`

**Needs:** 01 (fixtures, `httpx`), 04 (`parse_document` for version dates).

```markdown
## Goal

Describe the law library's sources in one config file and write the fetcher that downloads every point-in-time version of each listed section from legislation.gov.uk, politely and reproducibly, recording a hash for every file. Facts: docs/milestones/M3.md sections 4.2, 6.5 (fetch) and 6.6.

## In scope

- `law/sources.toml`: new, with `cra-2015` and `cca-1974` exactly as in M3.md 6.6, plus `limitation-1980` (`ukpga/1980/58`, sections `2`, `5`, `14A`, `32`, same metadata) unless `docs/SETUP_LOG.md` records decision D5 as "no".
- `src/alteram/law/fetch.py`: new.
  - `load_sources(path) -> dict[str, Source]` with `tomllib`; `Source` is a Pydantic model; unknown keys, a missing required key, or a `kind` other than `legislation`/`fca` are errors naming the source.
  - `section_url(base, section, version=None) -> str` (`.../section/<s>/data.xml` or `.../section/<s>/<YYYY-MM-DD>/data.xml`).
  - `fetch_source(source, raw_dir, client: httpx.Client, sleep, now, contact: str, refresh=False) -> FetchReport`: for each section, get the current XML, read `version_dates` with `alteram.law.legislation.parse_document`, then get each dated version. Files go to `raw_dir/<source>/<section>@<date>.xml` and `@current.xml`. Existing files are skipped unless `refresh`. Requests are sequential with `sleep(1.0)` between them. The User-Agent is `alteram/<package version> (+<contact>)`; `contact` comes from the caller (the CLI reads `ALTERAM_HTTP_CONTACT`), and an empty contact is an error. A non-200 stops the source with an error naming the URL. Finally it writes `raw_dir/<source>/fetch.json` (URL, file, sha256, fetched_at), sorted, and returns counts.
- `tests/test_fetch.py`: new; `httpx.MockTransport` serving files from `tests/fixtures/law/legislation/`, a fake `sleep` that records calls, a fixed `now`.

## Out of scope

- The CLI (step 15), parsing beyond calling `parse_document`, chunking.
- `.gitignore` (step 01 already ignores `law/raw/`), the fixture files.
- Any real network access in tests.

## Done when

1. `load_sources("law/sources.toml")` loads every source, and tests show each kind of config error is reported with the source name.
2. A fetch against the mock writes the current and every dated version for a fixture section, with `sleep(1.0)` called between every two requests and the User-Agent containing the contact.
3. A second fetch makes no requests; `refresh=True` refetches.
4. `fetch.json` lists every file with a sha256 that matches the bytes on disk, sorted by file name, and is identical across two runs with the same `now`.
5. A 404 or 503 from the mock raises an error naming the URL, and leaves no partial file.
6. `git diff --stat main` lists only the three files in scope.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 13

**Title:** `Task: M3-13 build step: raw legislation XML to chunks JSONL`

**Needs:** 04, 05, 12.

```markdown
## Goal

Join parser, version merging and chunker into the build step of ingestion: raw files of one source in, a deterministic `law/chunks/<source>.jsonl` and a report out, with no network and no model. Conventions: docs/milestones/M3.md section 6.5 (build).

## In scope

- `src/alteram/law/build.py`: new.
  - `build_source(name, sources, raw_dir, out_dir) -> BuildReport`: reads `raw_dir/<name>/fetch.json`, parses every listed file with `parse_document`, passes each file's sha256 through as `source_sha256`, merges with `merge_versions`, builds chunks with `to_chunks` and the source's metadata and topics, and writes `out_dir/<name>.jsonl` (one `LawChunk` per line, sorted by ID, UTF-8, trailing newline).
  - A file's sha256 that doesn't match `fetch.json` stops the build with an error naming the file.
  - `BuildReport`: chunk count, version dates, provisions skipped (by reason), unapplied effects per provision, and the path written.
  - `read_chunks(path) -> list[LawChunk]`.
- `tests/test_law_build.py`: new; builds a temporary raw dir from the files in `tests/fixtures/law/legislation/` and a `fetch.json` written by the test.

## Out of scope

- Headers, embeddings, storage, CLI, the FCA parser (step 19 adds `kind = "fca"`).
- Changes to `legislation.py`, `chunk.py` or `fetch.py`. If one is needed, name it in the plan and stop.

## Done when

1. Building from the CCA s.75 fixtures yields chunks whose spans match the fixture versions, and every chunk validates as a `LawChunk`.
2. Running the build twice gives byte-identical JSONL.
3. A tampered raw file stops the build with its name in the error.
4. `read_chunks` round-trips what was written.
5. The report lists the CRA s.12 unapplied effect and the skipped provisions from the s.140A base-date fixture.
6. `git diff --stat main` lists only the two files in scope.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 14

**Title:** `Task: M3-14 header and load steps: headers, embed changed chunks, upsert, manifest`

**Needs:** 06, 07, 08, 11.

```markdown
## Goal

Write the paid half of ingestion as testable functions: add contextual headers to built chunks, then embed only what changed, upsert into a `LawStore`, remove stale rows and update the manifest, all with a dry-run and a budget. Conventions: docs/milestones/M3.md section 6.5 (headers, load, costs).

## In scope

- `src/alteram/law/load.py`: new.
  - `add_headers(chunks, writer: HeaderWriter, dry_run=False, limit=None) -> HeaderReport`: groups chunks by `in_force_from`, builds the document context once per group with `document_context`, writes headers, sets `text_contextual` with `contextual_text`. In dry-run it reports calls needed (cache misses) and worst-case cost and makes no calls. `limit` caps the number of model calls.
  - `load_source(name, chunks, store, embedder, manifest_path, budget, entry_meta, dry_run=False) -> LoadReport`: first `check_embedding` against the manifest and `store.embedding_models()`; every chunk must have `text_contextual`; a chunk counts as changed when `store.get(id)` is missing or its `chunk_sha256`, `text_contextual` or `embedding_model` differs. It embeds only changed chunks (`embed_documents`), checks the budget with `embedding_cost_usd` before each batch, upserts all, removes `store.ids(name)` not in the build, and writes the manifest entry (via `update_source`). Dry-run makes no embedding calls and no writes and reports what would happen.
  - Reports include calls, tokens and cost in USD.
- `tests/test_law_load.py`: new; `MemoryStore`, `FakeEmbedder`, `GenericFakeChatModel`, `tmp_path`.

## Out of scope

- The CLI (step 15), Postgres, real models.
- Changes to the modules this one uses. If one is needed, name it in the plan and stop.

## Done when

1. A first load embeds every chunk; a second load of the same chunks makes zero embedding calls and reports $0.00.
2. Changing one chunk's text re-embeds exactly that chunk; dropping a chunk from the build removes it from the store.
3. A manifest with another embedding model stops the load before any call, naming the source.
4. Dry-run of both steps makes no calls and no writes (store, cache and manifest unchanged) and reports the counts the real run then makes.
5. A budget too small for the second batch stops after the first, with the store holding only fully processed batches and the error naming the budget.
6. `limit=5` makes at most five header calls.
7. `git diff --stat main` lists only the two files in scope.
8. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 15

**Title:** `Task: M3-15 alteram law fetch, build, headers, load and ingest commands`

**Needs:** 09, 13, 14.

```markdown
## Goal

Expose ingestion as `alteram law` subcommands so Gabriel can run each step, or all of them, from the terminal, with each command needing only the environment variables it uses. Conventions: docs/milestones/M3.md section 6.5 and the variables in section 6.7.

## In scope

- `src/alteram/law/cli.py`: new. `add_law_parser(subparsers)` and `run_law(args) -> int` for:
  - `fetch <source> [--refresh]` (needs `ALTERAM_HTTP_CONTACT`);
  - `build <source>` (no variables);
  - `headers <source> [--dry-run] [--limit N] [--budget USD]` (needs `ALTERAM_HEADER_MODEL` and `ANTHROPIC_API_KEY`, except in dry-run, which needs only `ALTERAM_HEADER_MODEL`);
  - `load <source> [--dry-run] [--budget USD]` (needs `ALTERAM_EMBEDDING_MODEL`, `ALTERAM_DATABASE_URL`, and `VOYAGE_API_KEY` except in dry-run);
  - `ingest <source> [--dry-run] [--refresh] [--limit N] [--budget USD]` (all of the above, in order; the budget covers the whole run).
  - Defaults: `law/sources.toml`, `law/raw/`, `law/chunks/`, `law/cache/headers.jsonl`, `law/manifest.json`, `--budget 5`.
  - Missing variables are reported together, by name only, with exit code 2. Reports print counts and cost; errors print one line and exit 1.
  - Construction of real clients (httpx, `VoyageEmbedder`, the Anthropic chat model, `PostgresStore`) sits in small factory functions that tests replace with fakes through `monkeypatch`.
- `src/alteram/cli.py`: add the `law` subcommand, dispatched to `run_law` before any check of `ALTERAM_LAWYER_MODEL`, `ALTERAM_JUDGE_MODEL` or `ANTHROPIC_API_KEY` that other commands need. No other behaviour change.
- `tests/test_law_cli.py`: new.

## Out of scope

- `show`, `search` and `status` (step 16), README and AGENTS.md (step 16).
- Changes to the law modules this one calls.

## Done when

1. `uv run alteram law --help` lists the five commands, and every existing command's `--help` is unchanged (compare with `main` in a test or in the plan's check).
2. With no variables set, `alteram law build cra-2015` runs (on a temp raw dir in the test), and `alteram law load cra-2015` exits 2 naming the three missing variables without printing any value.
3. `ingest --dry-run`, with fakes patched in, prints calls and cost and leaves the store, cache and manifest unchanged.
4. `ingest` with fakes runs all four steps in order, and a second run reports 0 header calls, 0 embedding calls and $0.00.
5. Existing `run`, `swap`, `rejudge`, `eval` and `cases` tests still pass unchanged.
6. `git diff --stat main` lists only the three files in scope.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 16

**Title:** `Task: M3-16 law library inspector: alteram law show, search and status`

**Needs:** 15.

```markdown
## Goal

Let Gabriel look inside the law library from the terminal (the M3 stand-in for the console's library inspector, decision D1 in docs/milestones/M3.md): one chunk in full, raw keyword and vector hits for a query on a date, and the state of each source against the manifest.

## In scope

- `src/alteram/law/inspect.py`: new; formatting functions that take data and return strings, so they are tested without a terminal:
  - `format_chunk(stored_chunk) -> str`: ID, heading path, validity (`from … to …` or `from … (current)`), source URL, licence and attribution, topics, holdout, then **Original text** and **Contextual header** as separate labelled blocks.
  - `format_hits(keyword_hits, vector_hits, chunks_by_id) -> str`: two lists side by side or one after the other, each line with rank, score, backend, ID and the first 80 characters of the original text.
  - `format_status(counts, store_models, manifest) -> str`: one line per source with stored count, manifest count, embedding model, and `OK` or the mismatch.
- `src/alteram/law/cli.py`: add `show <id>` (needs `ALTERAM_DATABASE_URL`); `search "<query>" --as-of YYYY-MM-DD [--k 10] [--keyword-only]` (keyword search needs only the database; vector search also needs `VOYAGE_API_KEY` and `ALTERAM_EMBEDDING_MODEL`, and without them it runs keyword-only and says so); `status` (database and manifest). Unknown ID: exit 1 with a one-line message.
- `tests/test_law_inspect.py`: new; `tests/test_law_cli.py`: add tests for the three commands with `MemoryStore` and `FakeEmbedder` patched in.
- `README.md`: a "Law library" subsection under "Use" with the commands from M3.md section 6.5 and these three, and a pointer to docs/milestones/M3.md for setup.
- `AGENTS.md`: add the `alteram law ...` commands to the Commands block. Nothing else in AGENTS.md changes.

## Out of scope

- Any web or console code (M2).
- Fusion, reranking or the relevance gate (M4): show raw hits only.
- Changes to the ingest commands.

## Done when

1. `format_chunk` output shows the original text and the header under separate labels, and the original appears verbatim.
2. `search --as-of` on a `MemoryStore` holding two versions of one provision shows only the version in force on that date, and the other version for a date after the change.
3. `search` without Voyage variables prints a note and keyword hits only, and exits 0.
4. `status` reports `OK` when the store and manifest agree, and names the source on a count or model mismatch.
5. Every command shown in README's "Law library" subsection exists in `alteram law --help`.
6. `git diff --stat main` lists only the files in scope.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```

---

## Issue 19

**Title:** `Task: M3-19 FCA Handbook parser and build integration`

**Needs:** 13, 18. **Step 18 must finish this issue first:** replace every line marked `[18]` with the facts it established, and delete this note.

```markdown
## Goal

Add FCA Handbook rules (CONC and DISP) to the law library from files saved by hand, never fetched by a script, so the same build, header and load steps handle them. Conventions: docs/milestones/M3.md sections 3.2, 4.3 and 6.2 (FCA IDs).

## In scope

- `src/alteram/law/fca.py`: new. `parse_fca_file(data: bytes, source: str) -> list[Provision]`:
  - [18] File format and the elements or text patterns that mark a rule, its number and status letter (R, G, E, D), and its text.
  - One provision per rule or guidance paragraph, `uri_path` `fca/<SOURCEBOOK>/<rule>` (e.g. `fca/DISP/2.8.2R`); heading path: sourcebook title > chapter > section > rule number.
  - `in_force_from`: [18] where the in-force or "as at" date appears in the saved file. `in_force_to` None.
  - `authority_tier` on each `Provision`: `regulation` for R and E, `guidance` for G (the chunker already prefers a provision's tier over the source's).
- `src/alteram/law/build.py`: for sources with `kind = "fca"`, read files from `law/raw/<source>/` listed in a hand-written `manifest.txt` (file name and sha256 per line) and use `parse_fca_file`; legislation sources unchanged.
- `law/sources.toml`: add `fca-conc` and `fca-disp` ([18] chapters chosen under D3), `doc_type = "regulation"`, licence and attribution as decided in step 18.
- `tests/test_fca.py`: new, on `tests/fixtures/law/fca/`. `tests/test_law_build.py`: add an FCA build test.

## Out of scope

- Any code that downloads from fca.org.uk or handbook.fca.org.uk.
- The fixture files (step 18 committed them).
- `pyproject.toml`, `uv.lock` (if step 18 added a parser dependency, it is already there).

## Done when

1. DISP 2.8.2R in the fixture parses to a provision with ID prefix `fca/DISP/2.8.2R/`, its full rule text (checked against a string in the test), and the fixture's date.
2. Guidance paragraphs get `authority_tier = "guidance"` and rules `regulation` (tested).
3. No provision text contains navigation, footer, or "print" text from the saved page (a test checks for a few known strings, [18]).
4. Building an FCA source twice gives byte-identical JSONL, and legislation build tests pass unchanged.
5. No module under `src/alteram/law/` imports `httpx` for FCA paths (a test greps `fca.py`).
6. `git diff --stat main` lists only the files in scope.
7. `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass, with more tests collected than on `main`.
```
