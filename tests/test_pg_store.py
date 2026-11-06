"""PostgresStore: SQL builders as strings and params, plus db-only behaviour."""

import inspect
import itertools
from datetime import date

import conftest
import psycopg
import pytest
from test_law_store import MODEL, make_chunk, vec

from alteram import db
from alteram.law.models import SearchFilters
from alteram.law.pg_store import (
    VALIDITY_CLAUSE,
    PostgresStore,
    filter_clauses,
    keyword_query,
    keyword_search_sql,
    vector_literal,
    vector_search_sql,
)

MARKERS = {
    "doc_types": "zz_doc_marker",
    "jurisdictions": "zz_jur_marker",
    "sources": "zz_src_marker",
    "topics": "zz_topic_marker",
}


def all_filters() -> list[SearchFilters]:
    names = list(MARKERS)
    found = []
    for flags in itertools.product([False, True], repeat=len(names)):
        values = {
            n: frozenset({MARKERS[n]}) for n, on in zip(names, flags, strict=True) if on
        }
        found.append(SearchFilters(**values))
    return found


@pytest.mark.parametrize("build", [vector_search_sql, keyword_search_sql])
@pytest.mark.parametrize("filters", all_filters())
def test_sql_always_has_validity_and_holdout(build, filters: SearchFilters) -> None:
    sql, params = build(filters)
    assert VALIDITY_CLAUSE in sql
    assert "holdout = false" in sql
    assert sql.rstrip().endswith("LIMIT %(k)s")
    for name, marker in MARKERS.items():
        assert marker not in sql
        if getattr(filters, name) is not None:
            assert params[name] == [marker]
        else:
            assert name not in params


def test_filter_clauses_empty_when_no_filters() -> None:
    assert filter_clauses(SearchFilters()) == ([], {})


def test_vector_sql_uses_cosine_distance() -> None:
    sql, _ = vector_search_sql(SearchFilters())
    assert "embedding <=> %(v)s::vector" in sql
    assert "1 - (embedding <=> %(v)s::vector) AS score" in sql
    assert "embedding IS NOT NULL" in sql


def test_keyword_sql_uses_websearch_and_ts_rank_cd() -> None:
    sql, _ = keyword_search_sql(SearchFilters())
    assert "websearch_to_tsquery('english', %(q)s)" in sql
    assert "ts_rank_cd(search_tsv" in sql
    assert "search_tsv @@" in sql


def test_vector_literal() -> None:
    assert vector_literal([0.1, 2, -3.5]) == "[0.1,2.0,-3.5]"


def test_keyword_query_ors_distinct_content_words() -> None:
    assert keyword_query("The goods, GOODS and satisfactory!") == (
        "goods or satisfactory"
    )
    assert keyword_query("the of") == ""
    assert keyword_query("a; DROP -x") == "drop or x"


def test_empty_keyword_query_and_zero_k_make_no_sql() -> None:
    class Boom:
        def cursor(self, *args, **kwargs):
            raise AssertionError("no SQL expected")

    store = PostgresStore(Boom())  # type: ignore[arg-type]
    assert store.search_keyword("the of", date(2024, 1, 1), 5) == []
    assert store.search_keyword("goods", date(2024, 1, 1), 0) == []
    assert store.search_vector(vec(1), date(2024, 1, 1), 0) == []


def test_postgres_backend_name() -> None:
    assert PostgresStore.backend == "postgres"


def test_upsert_with_embeddings_but_no_model_raises_before_sql() -> None:
    store = PostgresStore(None)  # type: ignore[arg-type]
    chunk = make_chunk("1")
    with pytest.raises(ValueError):
        store.upsert([chunk], {chunk.id: vec(1)}, None)


# --- db.py ------------------------------------------------------------------


def test_database_url_unset_names_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALTERAM_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="ALTERAM_DATABASE_URL"):
        db.database_url()


def test_database_url_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALTERAM_DATABASE_URL", "postgresql://u@h/alteram")
    assert db.database_url() == "postgresql://u@h/alteram"


def test_test_database_url_unset_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALTERAM_TEST_DATABASE_URL", raising=False)
    assert db.test_database_url() is None


def test_test_database_url_rejects_non_test_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALTERAM_TEST_DATABASE_URL", "postgresql://u@h:5432/alteram")
    with pytest.raises(RuntimeError, match="_test"):
        db.test_database_url()


def test_test_database_url_accepts_test_name(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql://u@h:5432/alteram_test"
    monkeypatch.setenv("ALTERAM_TEST_DATABASE_URL", url)
    assert db.test_database_url() == url


# --- the pg_conn fixture ----------------------------------------------------


def test_pg_conn_skips_without_test_database(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALTERAM_TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("ALTERAM_REQUIRE_DB", raising=False)
    pytester.makeconftest(_CONFTEST)
    pytester.makepyfile("def test_x(pg_conn):\n    pass\n")
    result = pytester.runpytest("-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*no test database*"])


def test_pg_conn_fails_when_database_required(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALTERAM_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("ALTERAM_REQUIRE_DB", "1")
    pytester.makeconftest(_CONFTEST)
    pytester.makepyfile("def test_x(pg_conn):\n    pass\n")
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*ALTERAM_REQUIRE_DB=1*"])


_CONFTEST = (
    "import os\nimport pytest\nfrom alteram import db\n\n"
    + inspect.getsource(conftest.require_test_database)
    + "\n\n@pytest.fixture\ndef pg_conn():\n    require_test_database()\n"
)


# --- db-only behaviour ------------------------------------------------------


@pytest.mark.db
def test_search_tsv_is_generated_from_contextual_text(
    pg_conn: psycopg.Connection,
) -> None:
    store = PostgresStore(pg_conn)
    plain = make_chunk("1", text_original="Goods must be satisfactory.")
    ctx = make_chunk("2", text_contextual="Header about rejection.\n\nGoods.")
    store.upsert([plain, ctx], {}, None)
    rows = dict(pg_conn.execute("SELECT id, search_tsv::text FROM law_chunks"))
    assert "satisfactori" in rows[plain.id]
    assert "reject" in rows[ctx.id]
    assert "satisfactori" not in rows[ctx.id]


@pytest.mark.db
def test_check_rejects_embedding_without_model(pg_conn: psycopg.Connection) -> None:
    store = PostgresStore(pg_conn)
    chunk = make_chunk("1")
    store.upsert([chunk], {chunk.id: vec(1)}, MODEL)
    with pytest.raises(psycopg.errors.CheckViolation):
        pg_conn.execute("UPDATE law_chunks SET embedding_model = NULL")


@pytest.mark.db
def test_check_rejects_bad_validity_span(pg_conn: psycopg.Connection) -> None:
    store = PostgresStore(pg_conn)
    store.upsert([make_chunk("1")], {}, None)
    with pytest.raises(psycopg.errors.CheckViolation):
        pg_conn.execute("UPDATE law_chunks SET in_force_to = in_force_from")


@pytest.mark.db
def test_check_rejects_unknown_doc_type(pg_conn: psycopg.Connection) -> None:
    store = PostgresStore(pg_conn)
    store.upsert([make_chunk("1")], {}, None)
    with pytest.raises(psycopg.errors.CheckViolation):
        pg_conn.execute("UPDATE law_chunks SET doc_type = 'blog'")
