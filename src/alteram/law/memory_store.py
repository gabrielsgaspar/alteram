"""In-memory LawStore: the fake used in tests (docs/milestones/M3.md 6.4)."""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime

from alteram.law.models import (
    LawChunk,
    SearchFilters,
    SearchHit,
    StoredChunk,
    in_force_on,
)
from alteram.law.store import NO_FILTERS, LawStore, cosine, normalise_query

_WORD = re.compile(r"[a-z0-9]+")


class MemoryStore(LawStore):
    backend = "memory"

    def __init__(self) -> None:
        self._chunks: dict[str, StoredChunk] = {}
        self._embeddings: dict[str, list[float]] = {}

    def upsert(
        self,
        chunks: Sequence[LawChunk],
        embeddings: Mapping[str, Sequence[float]],
        embedding_model: str | None,
    ) -> int:
        if embeddings and embedding_model is None:
            raise ValueError("embedding_model is required when embeddings are given")
        now = datetime.now(UTC)
        for chunk in chunks:
            has_embedding = chunk.id in embeddings
            self._chunks[chunk.id] = StoredChunk(
                **chunk.model_dump(),
                embedding_model=embedding_model if has_embedding else None,
                ingested_at=now,
            )
            if has_embedding:
                self._embeddings[chunk.id] = list(embeddings[chunk.id])
            else:
                self._embeddings.pop(chunk.id, None)
        return len(chunks)

    def get(self, chunk_id: str) -> StoredChunk | None:
        return self._chunks.get(chunk_id)

    def ids(self, source: str) -> set[str]:
        return {c.id for c in self._chunks.values() if c.source == source}

    def remove(self, chunk_ids: Iterable[str]) -> int:
        removed = 0
        for chunk_id in set(chunk_ids):
            if self._chunks.pop(chunk_id, None) is not None:
                removed += 1
            self._embeddings.pop(chunk_id, None)
        return removed

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for chunk in self._chunks.values():
            result[chunk.source] = result.get(chunk.source, 0) + 1
        return result

    def embedding_models(self) -> set[str]:
        return {c.embedding_model for c in self._chunks.values() if c.embedding_model}

    def _candidates(self, as_of: date, filters: SearchFilters) -> list[StoredChunk]:
        found = []
        for c in self._chunks.values():
            if c.holdout or not in_force_on(c, as_of):
                continue
            if filters.doc_types is not None and c.doc_type not in filters.doc_types:
                continue
            if (
                filters.jurisdictions is not None
                and c.jurisdiction not in filters.jurisdictions
            ):
                continue
            if filters.sources is not None and c.source not in filters.sources:
                continue
            if filters.topics is not None and not filters.topics.intersection(c.topics):
                continue
            found.append(c)
        return found

    @staticmethod
    def _rank(scored: list[tuple[str, float]], k: int) -> list[SearchHit]:
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [
            SearchHit(chunk_id=cid, score=score, rank=i, backend="memory")
            for i, (cid, score) in enumerate(scored[: max(k, 0)], start=1)
        ]

    def search_vector(
        self,
        embedding: Sequence[float],
        as_of: date,
        k: int,
        filters: SearchFilters = NO_FILTERS,
    ) -> list[SearchHit]:
        scored = [
            (c.id, cosine(embedding, self._embeddings[c.id]))
            for c in self._candidates(as_of, filters)
            if c.id in self._embeddings
        ]
        return self._rank(scored, k)

    def search_keyword(
        self, query: str, as_of: date, k: int, filters: SearchFilters = NO_FILTERS
    ) -> list[SearchHit]:
        words = set(normalise_query(query))
        if not words:
            return []
        scored = []
        for c in self._candidates(as_of, filters):
            text = (c.text_contextual or c.text_original).lower()
            score = len(words.intersection(_WORD.findall(text)))
            if score > 0:
                scored.append((c.id, float(score)))
        return self._rank(scored, k)
