"""Embedders: Voyage through httpx.MockTransport only, and the fake."""

import json
import math
from collections.abc import Callable

import httpx
import pytest

from alteram.law.embed import (
    FakeEmbedder,
    VoyageEmbedder,
    batch_texts,
)

KEY = "test-key-abc123"
DIM = 4


def vec(i: int) -> list[float]:
    return [float(i)] * DIM


def ok_response(request: httpx.Request, dim: int = DIM, shuffle: bool = False):
    texts = json.loads(request.content)["input"]
    data = [{"index": i, "embedding": [float(i)] * dim} for i in range(len(texts))]
    if shuffle:
        data.reverse()
    return httpx.Response(
        200, json={"data": data, "usage": {"total_tokens": len(texts) * 2}}
    )


def make(
    handler: Callable[[httpx.Request], httpx.Response],
    sleeps: list[float] | None = None,
) -> VoyageEmbedder:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    record = sleeps if sleeps is not None else []
    return VoyageEmbedder(
        "voyage-4-large",
        dimension=DIM,
        api_key=KEY,
        client=client,
        sleep=record.append,
    )


def test_request_body_header_and_order() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok_response(request, shuffle=True)

    result = make(handler).embed_documents(["a", "b", "c"])
    body = json.loads(seen[0].content)
    assert body["model"] == "voyage-4-large"
    assert body["input_type"] == "document"
    assert body["output_dimension"] == DIM
    assert body["input"] == ["a", "b", "c"]
    assert seen[0].headers["Authorization"] == f"Bearer {KEY}"
    assert result.vectors == [vec(0), vec(1), vec(2)]
    assert result.total_tokens == 6


def test_query_uses_query_input_type() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return ok_response(request)

    result = make(handler).embed_query("hello")
    assert seen[0]["input_type"] == "query"
    assert len(result.vectors) == 1


def test_300_texts_are_split_into_batches_of_at_most_128() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sizes.append(len(json.loads(request.content)["input"]))
        return ok_response(request)

    result = make(handler).embed_documents([f"t{i}" for i in range(300)])
    assert len(sizes) >= 3
    assert max(sizes) <= 128
    assert sum(sizes) == 300
    assert len(result.vectors) == 300
    assert result.total_tokens == 600


def test_batching_by_estimated_tokens() -> None:
    big = "x" * 200_000  # 50,000 estimated tokens
    batches = batch_texts([big, big, big])
    assert [len(b) for b in batches] == [2, 1]
    assert batch_texts([]) == []
    # A lone oversized text still goes out, alone.
    assert batch_texts(["y" * 500_000, "z"]) == [["y" * 500_000], ["z"]]


def test_retries_429_with_backoff_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= 2:
            return httpx.Response(429)
        return ok_response(request)

    sleeps: list[float] = []
    result = make(handler, sleeps).embed_documents(["a"])
    assert calls == 3
    assert len(sleeps) == 2
    assert sleeps[1] == 2 * sleeps[0]
    assert len(result.vectors) == 1


def test_persistent_500_raises_without_the_key() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, text=f"boom {KEY}")

    sleeps: list[float] = []
    with pytest.raises(RuntimeError) as excinfo:
        make(handler, sleeps).embed_documents(["a"])
    assert calls == 5
    assert len(sleeps) == 4
    assert KEY not in str(excinfo.value)
    assert "500" in str(excinfo.value)


def test_other_4xx_fails_at_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    sleeps: list[float] = []
    with pytest.raises(RuntimeError, match="401"):
        make(handler, sleeps).embed_documents(["a"])
    assert calls == 1
    assert sleeps == []


def test_wrong_vector_length_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return ok_response(request, dim=DIM + 1)

    with pytest.raises(RuntimeError, match="dimensions"):
        make(handler).embed_documents(["a"])


def test_key_comes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "env-key")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok_response(request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    VoyageEmbedder("voyage-4-large", dimension=DIM, client=client).embed_query("a")
    assert seen[0].headers["Authorization"] == "Bearer env-key"


def test_missing_key_raises_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    client = httpx.Client(transport=httpx.MockTransport(ok_response))
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        VoyageEmbedder("voyage-4-large", client=client)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_fake_is_deterministic_and_unit_length() -> None:
    fake = FakeEmbedder()
    one = fake.embed_documents(["Satisfactory quality goods"]).vectors[0]
    two = fake.embed_query("satisfactory quality goods").vectors[0]
    assert one == two
    assert len(one) == fake.dimension == 1024
    assert math.sqrt(sum(v * v for v in one)) == pytest.approx(1.0)


def test_fake_shared_words_raise_cosine() -> None:
    fake = FakeEmbedder()
    base, near, far = fake.embed_documents(
        [
            "satisfactory quality goods",
            "goods of satisfactory quality",
            "limitation period expired",
        ]
    ).vectors
    assert cosine(base, near) > cosine(base, far)


def test_fake_counts_words_as_tokens() -> None:
    result = FakeEmbedder(dimension=8).embed_documents(["one two three", "four"])
    assert result.total_tokens == 4
    assert len(result.vectors) == 2


def test_fake_empty_text_gives_zero_vector() -> None:
    result = FakeEmbedder(dimension=8).embed_query("")
    assert result.vectors == [[0.0] * 8]
    assert result.total_tokens == 0
