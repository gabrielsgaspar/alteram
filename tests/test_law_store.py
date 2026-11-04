"""Contract tests for LawStore, plus MemoryStore-specific tests at the end."""

from datetime import date
from typing import Any

import pytest

from alteram.law.memory_store import MemoryStore
from alteram.law.models import (
    LawChunk,
    SearchFilters,
    chunk_sha256,
    library_id,
)
from alteram.law.store import STOP_WORDS, LawStore, cosine, normalise_query

DIM = 1024
MODEL = "test-model"
AS_OF = date(2024, 1, 1)


def vec(*values: float) -> list[float]:
    """A vector padded with zeros to the dimension Postgres will use."""
    return [*values, *([0.0] * (DIM - len(values)))]


def make_chunk(section: str = "9", **overrides: Any) -> LawChunk:
    in_force_from = overrides.pop("in_force_from", date(2015, 10, 1))
    part = overrides.pop("part", None)
    heading_path = overrides.pop("heading_path", ["Consumer Rights Act 2015"])
    text = overrides.pop("text_original", f"Goods must be of quality {section}.")
    values: dict[str, Any] = {
        "id": library_id(f"ukpga/2015/15/section/{section}", in_force_from, part),
        "source": "cra-2015",
        "source_url": "https://www.legislation.gov.uk/ukpga/2015/15",
        "doc_type": "statute",
        "authority_tier": "statute",
        "jurisdiction": "uk",
        "extent": None,
        "heading_path": heading_path,
        "in_force_from": in_force_from,
        "in_force_to": None,
        "text_original": text,
        "text_contextual": None,
        "topics": [],
        "holdout": False,
        "licence": "OGL-3.0",
        "attribution": "Crown copyright",
        "source_sha256": "0" * 64,
        "chunk_sha256": chunk_sha256(heading_path, text),
    }
    values.update(overrides)
    return LawChunk(**values)


@pytest.fixture(params=["memory"])
def store(request: pytest.FixtureRequest) -> LawStore:
    if request.param == "memory":
        return MemoryStore()
    raise AssertionError(request.param)


def hit_ids(hits: list[Any]) -> list[str]:
    return [h.chunk_id for h in hits]


# --- Contract tests ---------------------------------------------------------


def test_as_of_boundaries(store: LawStore) -> None:
    chunk = make_chunk(in_force_from=date(2020, 1, 10), in_force_to=date(2020, 2, 10))
    store.upsert([chunk], {chunk.id: vec(1)}, MODEL)
    cases = [
        (date(2020, 1, 9), False),
        (date(2020, 1, 10), True),
        (date(2020, 2, 9), True),
        (date(2020, 2, 10), False),
    ]
    for as_of, expected in cases:
        vector_hits = store.search_vector(vec(1), as_of, 5)
        keyword_hits = store.search_keyword("goods", as_of, 5)
        assert (hit_ids(vector_hits) == [chunk.id]) is expected, as_of
        assert (hit_ids(keyword_hits) == [chunk.id]) is expected, as_of


def test_holdout_hidden_from_search_but_get_works(store: LawStore) -> None:
    held = make_chunk("9", holdout=True)
    store.upsert([held], {held.id: vec(1)}, MODEL)
    assert store.search_vector(vec(1), AS_OF, 5) == []
    assert store.search_keyword("goods", AS_OF, 5) == []
    found = store.get(held.id)
    assert found is not None
    assert found.holdout is True


def test_get_missing_returns_none(store: LawStore) -> None:
    assert store.get("ukpga/2015/15/section/1/2015-10-01") is None


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (SearchFilters(doc_types=frozenset({"regulation"})), ["b"]),
        (SearchFilters(jurisdictions=frozenset({"england_wales"})), ["c"]),
        (SearchFilters(sources=frozenset({"other"})), ["d"]),
        (SearchFilters(topics=frozenset({"remedy"})), ["e"]),
        (SearchFilters(topics=frozenset({"remedy", "nothing"})), ["e"]),
    ],
)
def test_each_filter_field(
    store: LawStore, filters: SearchFilters, expected: list[str]
) -> None:
    chunks = {
        "a": make_chunk("1"),
        "b": make_chunk("2", doc_type="regulation"),
        "c": make_chunk("3", jurisdiction="england_wales"),
        "d": make_chunk("4", source="other"),
        "e": make_chunk("5", topics=["remedy", "other_topic"]),
    }
    store.upsert(list(chunks.values()), {c.id: vec(1) for c in chunks.values()}, MODEL)
    want = [chunks[key].id for key in expected]
    assert hit_ids(store.search_vector(vec(1), AS_OF, 10, filters)) == want
    assert hit_ids(store.search_keyword("goods", AS_OF, 10, filters)) == want


def test_no_filters_returns_all(store: LawStore) -> None:
    chunks = [make_chunk(str(n)) for n in range(1, 4)]
    store.upsert(chunks, {c.id: vec(1) for c in chunks}, MODEL)
    assert len(store.search_vector(vec(1), AS_OF, 10)) == 3
    assert len(store.search_keyword("goods", AS_OF, 10)) == 3


def test_k_and_ranks_are_contiguous_from_one(store: LawStore) -> None:
    chunks = [make_chunk(str(n)) for n in range(1, 6)]
    store.upsert(chunks, {c.id: vec(1, n) for n, c in enumerate(chunks)}, MODEL)
    for hits in (
        store.search_vector(vec(1), AS_OF, 3),
        store.search_keyword("goods", AS_OF, 3),
    ):
        assert len(hits) == 3
        assert [h.rank for h in hits] == [1, 2, 3]
    assert len(store.search_vector(vec(1), AS_OF, 50)) == 5


def test_vector_search_orders_by_similarity(store: LawStore) -> None:
    near = make_chunk("1")
    far = make_chunk("2")
    store.upsert([near, far], {near.id: vec(1, 0.1), far.id: vec(0, 1)}, MODEL)
    hits = store.search_vector(vec(1), AS_OF, 5)
    assert hit_ids(hits) == [near.id, far.id]
    assert {h.backend for h in hits} == {store.backend}
    assert hits[0].score > hits[1].score


def test_vector_search_skips_chunks_without_embedding(store: LawStore) -> None:
    with_emb = make_chunk("1")
    without = make_chunk("2")
    store.upsert([with_emb, without], {with_emb.id: vec(1)}, MODEL)
    assert hit_ids(store.search_vector(vec(1), AS_OF, 5)) == [with_emb.id]
    assert set(hit_ids(store.search_keyword("goods", AS_OF, 5))) == {
        with_emb.id,
        without.id,
    }


def test_keyword_search_ranks_better_match_first(store: LawStore) -> None:
    both = make_chunk("1", text_original="Goods must be satisfactory.")
    one = make_chunk("2", text_original="Goods must be returned.")
    store.upsert([one, both], {}, None)
    hits = store.search_keyword("satisfactory goods", AS_OF, 5)
    assert hit_ids(hits) == [both.id, one.id]


def test_keyword_search_uses_contextual_text_when_present(store: LawStore) -> None:
    chunk = make_chunk("1", text_contextual="Header about rejection.\n\nGoods.")
    store.upsert([chunk], {}, None)
    assert hit_ids(store.search_keyword("rejection", AS_OF, 5)) == [chunk.id]


def test_keyword_search_no_match_or_empty_query(store: LawStore) -> None:
    store.upsert([make_chunk("1")], {}, None)
    assert store.search_keyword("zebra", AS_OF, 5) == []
    assert store.search_keyword("", AS_OF, 5) == []
    assert store.search_keyword("the of", AS_OF, 5) == []


def test_upsert_twice_leaves_one_row(store: LawStore) -> None:
    chunk = make_chunk("1")
    store.upsert([chunk], {chunk.id: vec(1)}, MODEL)
    store.upsert([chunk], {chunk.id: vec(1)}, MODEL)
    assert store.counts() == {"cra-2015": 1}
    assert store.ids("cra-2015") == {chunk.id}
    assert len(store.search_vector(vec(1), AS_OF, 10)) == 1


def test_upsert_returns_count(store: LawStore) -> None:
    chunks = [make_chunk("1"), make_chunk("2")]
    assert store.upsert(chunks, {}, None) == 2


def test_upsert_replaces_content(store: LawStore) -> None:
    old = make_chunk("1", text_original="Old wording.")
    new = make_chunk("1", text_original="New wording.")
    store.upsert([old], {}, None)
    store.upsert([new], {}, None)
    found = store.get(old.id)
    assert found is not None
    assert found.text_original == "New wording."


def test_upsert_without_embedding_drops_old_embedding(store: LawStore) -> None:
    chunk = make_chunk("1")
    store.upsert([chunk], {chunk.id: vec(1)}, MODEL)
    store.upsert([chunk], {}, None)
    assert store.search_vector(vec(1), AS_OF, 5) == []
    assert store.embedding_models() == set()


def test_embeddings_without_model_raise(store: LawStore) -> None:
    chunk = make_chunk("1")
    with pytest.raises(ValueError):
        store.upsert([chunk], {chunk.id: vec(1)}, None)
    assert store.get(chunk.id) is None


def test_get_returns_stored_chunk(store: LawStore) -> None:
    chunk = make_chunk("1")
    store.upsert([chunk], {chunk.id: vec(1)}, MODEL)
    found = store.get(chunk.id)
    assert found is not None
    assert found.id == chunk.id
    assert found.embedding_model == MODEL
    assert found.ingested_at is not None


def test_ids_and_remove(store: LawStore) -> None:
    a = make_chunk("1")
    b = make_chunk("2")
    c = make_chunk("3", source="other")
    store.upsert([a, b, c], {a.id: vec(1)}, MODEL)
    assert store.ids("cra-2015") == {a.id, b.id}
    assert store.ids("other") == {c.id}
    assert store.ids("missing") == set()
    assert store.remove([a.id, "nope/1/2/2020-01-01"]) == 1
    assert store.ids("cra-2015") == {b.id}
    assert store.get(a.id) is None
    assert store.search_vector(vec(1), AS_OF, 5) == []
    assert store.remove([a.id]) == 0


def test_counts(store: LawStore) -> None:
    assert store.counts() == {}
    store.upsert(
        [make_chunk("1"), make_chunk("2"), make_chunk("3", source="other")], {}, None
    )
    assert store.counts() == {"cra-2015": 2, "other": 1}


def test_embedding_models(store: LawStore) -> None:
    assert store.embedding_models() == set()
    a = make_chunk("1")
    b = make_chunk("2")
    c = make_chunk("3")
    store.upsert([a, b], {a.id: vec(1)}, "model-a")
    store.upsert([c], {c.id: vec(1)}, "model-b")
    assert store.embedding_models() == {"model-a", "model-b"}


def test_tie_break_by_id(store: LawStore) -> None:
    a = make_chunk("1")
    b = make_chunk("2")
    store.upsert([b, a], {a.id: vec(1), b.id: vec(1)}, MODEL)
    expected = sorted([a.id, b.id])
    assert hit_ids(store.search_vector(vec(1), AS_OF, 5)) == expected
    assert hit_ids(store.search_keyword("goods", AS_OF, 5)) == expected


# --- MemoryStore-specific tests ---------------------------------------------


def test_memory_store_backend() -> None:
    assert MemoryStore().backend == "memory"


def test_memory_keyword_score_is_distinct_word_count() -> None:
    store = MemoryStore()
    chunk = make_chunk("1", text_original="Goods goods GOODS satisfactory.")
    store.upsert([chunk], {}, None)
    hits = store.search_keyword("goods satisfactory goods", AS_OF, 5)
    assert hits[0].score == 2.0


def test_memory_vector_score_is_cosine() -> None:
    store = MemoryStore()
    chunk = make_chunk("1")
    store.upsert([chunk], {chunk.id: vec(1, 1)}, MODEL)
    hit = store.search_vector(vec(1), AS_OF, 5)[0]
    assert hit.score == pytest.approx(2**-0.5)


def test_memory_non_positive_k_returns_nothing() -> None:
    store = MemoryStore()
    chunk = make_chunk("1")
    store.upsert([chunk], {chunk.id: vec(1)}, MODEL)
    assert store.search_vector(vec(1), AS_OF, 0) == []


def test_cosine() -> None:
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)
    assert cosine([0, 0], [1, 0]) == 0.0
    with pytest.raises(ValueError):
        cosine([1], [1, 2])


def test_normalise_query() -> None:
    assert normalise_query("The Goods, of SATISFACTORY quality!") == [
        "goods",
        "satisfactory",
        "quality",
    ]
    assert normalise_query("") == []
    assert "the" in STOP_WORDS
