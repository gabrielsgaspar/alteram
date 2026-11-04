"""Text embeddings: one interface, a Voyage client over httpx, and a fake."""

import hashlib
import math
import os
import re
import time
from collections.abc import Callable, Sequence
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
VOYAGE_KEY_ENV = "VOYAGE_API_KEY"

MAX_BATCH_TEXTS = 128
MAX_BATCH_TOKENS = 100_000
CHARS_PER_TOKEN = 4  # a rough estimate, used only to size batches
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 1.0
TIMEOUT_SECONDS = 60.0


class Embedded(BaseModel):
    vectors: list[list[float]]
    total_tokens: int


class Embedder(Protocol):
    model: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> Embedded: ...

    def embed_query(self, text: str) -> Embedded: ...


class EmbeddingError(RuntimeError):
    """An embedding request failed. Never carries the key or headers."""


def batch_texts(texts: Sequence[str]) -> list[list[str]]:
    """Split texts into batches of at most 128 texts and ~100,000 tokens.

    A single text over the token limit goes alone; the API may reject it."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for text in texts:
        tokens = math.ceil(len(text) / CHARS_PER_TOKEN)
        if current and (
            len(current) >= MAX_BATCH_TEXTS
            or current_tokens + tokens > MAX_BATCH_TOKENS
        ):
            batches.append(current)
            current, current_tokens = [], 0
        current.append(text)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


class VoyageEmbedder:
    def __init__(
        self,
        model: str,
        dimension: int = 1024,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get(VOYAGE_KEY_ENV, "")
        if not key:
            raise EmbeddingError(f"set {VOYAGE_KEY_ENV} or pass api_key")
        self.model = model
        self.dimension = dimension
        self._key = key
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._sleep = sleep

    def embed_documents(self, texts: Sequence[str]) -> Embedded:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> Embedded:
        return self._embed([text], "query")

    def _embed(
        self, texts: Sequence[str], input_type: Literal["document", "query"]
    ) -> Embedded:
        vectors: list[list[float]] = []
        total_tokens = 0
        for batch in batch_texts(texts):
            body = self._post_with_retries(batch, input_type)
            data = sorted(body["data"], key=lambda item: item["index"])
            if len(data) != len(batch):
                raise EmbeddingError(
                    f"{self.model}: sent {len(batch)} texts, got {len(data)} vectors"
                )
            for item in data:
                vector = item["embedding"]
                if len(vector) != self.dimension:
                    raise EmbeddingError(
                        f"{self.model}: expected {self.dimension} dimensions, "
                        f"got {len(vector)}"
                    )
                vectors.append(vector)
            total_tokens += body["usage"]["total_tokens"]
        return Embedded(vectors=vectors, total_tokens=total_tokens)

    def _post_with_retries(self, batch: list[str], input_type: str) -> dict:
        payload = {
            "input": batch,
            "model": self.model,
            "input_type": input_type,
            "output_dimension": self.dimension,
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        for attempt in range(MAX_RETRIES + 1):
            response = self._client.post(VOYAGE_URL, json=payload, headers=headers)
            status = response.status_code
            if status == 200:
                return response.json()
            retryable = status == 429 or status >= 500
            if not retryable or attempt == MAX_RETRIES:
                raise EmbeddingError(
                    f"{self.model}: request failed with status {status}"
                )
            self._sleep(BACKOFF_BASE_SECONDS * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover


_WORD = re.compile(r"\w+")


class FakeEmbedder:
    """Deterministic bag-of-words vectors for tests: no network, no model."""

    def __init__(self, dimension: int = 1024, model: str = "fake-embedder") -> None:
        self.model = model
        self.dimension = dimension

    def embed_documents(self, texts: Sequence[str]) -> Embedded:
        return self._embed(texts)

    def embed_query(self, text: str) -> Embedded:
        return self._embed([text])

    def _embed(self, texts: Sequence[str]) -> Embedded:
        vectors: list[list[float]] = []
        total = 0
        for text in texts:
            words = _WORD.findall(text.lower())
            total += len(words)
            vectors.append(self._vector(words))
        return Embedded(vectors=vectors, total_tokens=total)

    def _vector(self, words: list[str]) -> list[float]:
        vector = [0.0] * self.dimension
        for word in words:
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:8], "big") % self.dimension] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector  # no words: the zero vector
        return [v / norm for v in vector]
