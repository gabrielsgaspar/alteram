"""Postgres LawStore (docs/milestones/M3.md 6.3 and 6.4).

The SQL is built by small pure functions so it can be tested as strings and
parameters without a database. Filter values only ever go into parameters.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row

from alteram.law.models import LawChunk, SearchFilters, SearchHit, StoredChunk
from alteram.law.store import NO_FILTERS, LawStore, normalise_query

VALIDITY_CLAUSE = (
    "in_force_from <= %(as_of)s::date "
    "AND (in_force_to IS NULL OR %(as_of)s::date < in_force_to)"
)

CHUNK_COLUMNS = (
    "id",
    "source",
    "source_url",
    "doc_type",
    "authority_tier",
    "jurisdiction",
    "extent",
    "heading_path",
    "in_force_from",
    "in_force_to",
    "text_original",
    "text_contextual",
    "topics",
    "holdout",
    "licence",
    "attribution",
    "source_sha256",
    "chunk_sha256",
    "embedding_model",
    "ingested_at",
)

_INSERT_COLUMNS = (
    *(c for c in CHUNK_COLUMNS if c != "ingested_at"),
    "embedding",
)


def vector_literal(values: Sequence[float]) -> str:
    """A pgvector text literal such as `[0.1,0.2]`."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def filter_clauses(filters: SearchFilters) -> tuple[list[str], dict[str, Any]]:
    """WHERE fragments and parameters for the filters that are set."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if filters.doc_types is not None:
        clauses.append("doc_type = ANY(%(doc_types)s::text[])")
        params["doc_types"] = sorted(filters.doc_types)
    if filters.jurisdictions is not None:
        clauses.append("jurisdiction = ANY(%(jurisdictions)s::text[])")
        params["jurisdictions"] = sorted(filters.jurisdictions)
    if filters.sources is not None:
        clauses.append("source = ANY(%(sources)s::text[])")
        params["sources"] = sorted(filters.sources)
    if filters.topics is not None:
        clauses.append("topics && %(topics)s::text[]")
        params["topics"] = sorted(filters.topics)
    return clauses, params


def _where(extra: list[str], filters: SearchFilters) -> tuple[str, dict[str, Any]]:
    clauses, params = filter_clauses(filters)
    all_clauses = [*extra, VALIDITY_CLAUSE, "holdout = false", *clauses]
    return " AND ".join(all_clauses), params


def vector_search_sql(filters: SearchFilters) -> tuple[str, dict[str, Any]]:
    """SQL and filter params for cosine search. Caller adds as_of, v and k."""
    where, params = _where(["embedding IS NOT NULL"], filters)
    sql = (
        "SELECT id, 1 - (embedding <=> %(v)s::vector) AS score FROM law_chunks "
        f"WHERE {where} "
        "ORDER BY embedding <=> %(v)s::vector, id LIMIT %(k)s"
    )
    return sql, params


def keyword_search_sql(filters: SearchFilters) -> tuple[str, dict[str, Any]]:
    """SQL and filter params for full-text search. Caller adds as_of, q and k."""
    where, params = _where(
        ["search_tsv @@ websearch_to_tsquery('english', %(q)s)"], filters
    )
    sql = (
        "SELECT id, ts_rank_cd(search_tsv, "
        "websearch_to_tsquery('english', %(q)s)) AS score FROM law_chunks "
        f"WHERE {where} "
        "ORDER BY score DESC, id LIMIT %(k)s"
    )
    return sql, params


def upsert_sql() -> str:
    names = ", ".join(_INSERT_COLUMNS)
    values = ", ".join(
        "%(embedding)s::vector" if c == "embedding" else f"%({c})s"
        for c in _INSERT_COLUMNS
    )
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _INSERT_COLUMNS if c != "id")
    return (
        f"INSERT INTO law_chunks ({names}, ingested_at) VALUES ({values}, now()) "
        f"ON CONFLICT (id) DO UPDATE SET {updates}, ingested_at = now()"
    )


GET_SQL = f"SELECT {', '.join(CHUNK_COLUMNS)} FROM law_chunks WHERE id = %(id)s"
IDS_SQL = "SELECT id FROM law_chunks WHERE source = %(source)s"
REMOVE_SQL = "DELETE FROM law_chunks WHERE id = ANY(%(ids)s::text[]) RETURNING id"
COUNTS_SQL = "SELECT source, count(*) AS n FROM law_chunks GROUP BY source"
MODELS_SQL = (
    "SELECT DISTINCT embedding_model FROM law_chunks WHERE embedding_model IS NOT NULL"
)


def keyword_query(text: str) -> str:
    """Distinct content words joined with `or`, so more matching words rank higher.

    Plain websearch_to_tsquery would AND the words; the contract (and
    MemoryStore) count how many words match instead.
    """
    return " or ".join(dict.fromkeys(normalise_query(text)))


class PostgresStore(LawStore):
    backend = "postgres"

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        chunks: Sequence[LawChunk],
        embeddings: Mapping[str, Sequence[float]],
        embedding_model: str | None,
    ) -> int:
        if embeddings and embedding_model is None:
            raise ValueError("embedding_model is required when embeddings are given")
        rows = []
        for chunk in chunks:
            row = chunk.model_dump()
            vector = embeddings.get(chunk.id)
            row["embedding"] = None if vector is None else vector_literal(vector)
            row["embedding_model"] = None if vector is None else embedding_model
            rows.append(row)
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.executemany(upsert_sql(), rows)
        return len(rows)

    def get(self, chunk_id: str) -> StoredChunk | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(GET_SQL, {"id": chunk_id})
            row = cur.fetchone()
        return None if row is None else StoredChunk(**row)

    def ids(self, source: str) -> set[str]:
        with self._conn.cursor() as cur:
            cur.execute(IDS_SQL, {"source": source})
            return {r[0] for r in cur.fetchall()}

    def remove(self, chunk_ids: Iterable[str]) -> int:
        ids = sorted(set(chunk_ids))
        if not ids:
            return 0
        with self._conn.cursor() as cur:
            cur.execute(REMOVE_SQL, {"ids": ids})
            return len(cur.fetchall())

    def counts(self) -> dict[str, int]:
        with self._conn.cursor() as cur:
            cur.execute(COUNTS_SQL)
            return {r[0]: r[1] for r in cur.fetchall()}

    def embedding_models(self) -> set[str]:
        with self._conn.cursor() as cur:
            cur.execute(MODELS_SQL)
            return {r[0] for r in cur.fetchall()}

    def _search(
        self, sql: str, params: dict[str, Any], backend: str
    ) -> list[SearchHit]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [
            SearchHit(chunk_id=r[0], score=float(r[1]), rank=i, backend=backend)  # type: ignore[arg-type]
            for i, r in enumerate(rows, start=1)
        ]

    def search_vector(
        self,
        embedding: Sequence[float],
        as_of: date,
        k: int,
        filters: SearchFilters = NO_FILTERS,
    ) -> list[SearchHit]:
        if k <= 0:
            return []
        sql, params = vector_search_sql(filters)
        params |= {"as_of": as_of, "v": vector_literal(embedding), "k": k}
        return self._search(sql, params, "pgvector")

    def search_keyword(
        self, query: str, as_of: date, k: int, filters: SearchFilters = NO_FILTERS
    ) -> list[SearchHit]:
        q = keyword_query(query)
        if k <= 0 or not q:
            return []
        sql, params = keyword_search_sql(filters)
        params |= {"as_of": as_of, "q": q, "k": k}
        return self._search(sql, params, "postgres_fts")
