"""The law store interface (docs/milestones/M3.md 6.4) and two small helpers."""

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Protocol

from alteram.law.models import LawChunk, SearchFilters, SearchHit, StoredChunk

STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "with",
    }
)

_WORD = re.compile(r"[a-z0-9]+")

NO_FILTERS = SearchFilters()  # frozen, so safe as a shared default


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 for a zero vector, ValueError if lengths differ."""
    if len(a) != len(b):
        raise ValueError(f"vector lengths differ: {len(a)} and {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def normalise_query(text: str) -> list[str]:
    """Lower-cased word tokens with stop words removed, in order."""
    return [w for w in _WORD.findall(text.lower()) if w not in STOP_WORDS]


class LawStore(Protocol):
    backend: str  # "memory" or "postgres"

    def upsert(
        self,
        chunks: Sequence[LawChunk],
        embeddings: Mapping[str, Sequence[float]],
        embedding_model: str | None,
    ) -> int: ...
    def get(self, chunk_id: str) -> StoredChunk | None: ...
    def ids(self, source: str) -> set[str]: ...
    def remove(self, chunk_ids: Iterable[str]) -> int: ...
    def search_vector(
        self,
        embedding: Sequence[float],
        as_of: date,
        k: int,
        filters: SearchFilters = NO_FILTERS,
    ) -> list[SearchHit]: ...
    def search_keyword(
        self, query: str, as_of: date, k: int, filters: SearchFilters = NO_FILTERS
    ) -> list[SearchHit]: ...
    def counts(self) -> dict[str, int]: ...  # chunks per source
    def embedding_models(self) -> set[str]: ...
