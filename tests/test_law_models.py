from datetime import date

import pytest
from pydantic import ValidationError

from alteram.law.models import (
    LawChunk,
    SearchFilters,
    SearchHit,
    StoredChunk,
    chunk_sha256,
    in_force_on,
    jurisdiction_from_extent,
    library_id,
    parse_library_id,
)

PATH = "ukpga/2015/15/section/9/1"
START = date(2015, 10, 1)


def test_library_id_plain_and_part() -> None:
    assert library_id(PATH, START) == "ukpga/2015/15/section/9/1/2015-10-01"
    assert library_id(PATH, START, part=2) == "ukpga/2015/15/section/9/1/2015-10-01~2"


@pytest.mark.parametrize(
    ("uri_path", "start", "part"),
    [
        (PATH, START, None),
        (PATH, START, 2),
        ("fca/DISP/2.8.2R", date(2025, 1, 1), None),
    ],
)
def test_library_id_round_trip(uri_path: str, start: date, part: int | None) -> None:
    assert parse_library_id(library_id(uri_path, start, part)) == (
        uri_path,
        start,
        part,
    )


def test_fca_id_form() -> None:
    assert (
        library_id("fca/DISP/2.8.2R", date(2025, 1, 1)) == "fca/DISP/2.8.2R/2025-01-01"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "2015-10-01",
        "ukpga/2015/15/section/9/1",
        "ukpga/2015/15/section/9/1/2015-13-01",
        "ukpga/2015/15/section/9/1/2015-1-1",
        "ukpga/2015/15/section/9/1/2015-10-01~0",
        "ukpga/2015/15/section/9/1/2015-10-01~x",
        "ukpga/2015/15/section/9/1/2015-10-01~",
        "ukpga/2015//15/2015-10-01",
        "ukpga/2015/2015-10-01",
        "fca/DISP/2015-10-01",
        "fca/DISP/2.8.2R/extra/2025-01-01",
    ],
)
def test_parse_library_id_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_library_id(bad)


@pytest.mark.parametrize(
    ("uri_path", "part"), [("", None), (PATH + "/", None), (PATH, 0)]
)
def test_library_id_rejects_bad_input(uri_path: str, part: int | None) -> None:
    with pytest.raises(ValueError):
        library_id(uri_path, START, part)


class _Span:
    def __init__(self, start: date, end: date | None) -> None:
        self.in_force_from = start
        self.in_force_to = end


def test_in_force_on_boundaries() -> None:
    span = _Span(date(2020, 1, 1), date(2022, 1, 1))
    assert in_force_on(span, date(2020, 1, 1))
    assert not in_force_on(span, date(2019, 12, 31))
    assert not in_force_on(span, date(2022, 1, 1))
    assert in_force_on(span, date(2021, 12, 31))


def test_in_force_on_open_ended() -> None:
    assert in_force_on(_Span(date(2020, 1, 1), None), date(2999, 1, 1))


@pytest.mark.parametrize(
    ("extent", "expected"),
    [
        ("E+W+S+N.I.", "uk"),
        ("E+W", "england_wales"),
        ("E+W+S", "great_britain"),
        (None, "unknown"),
    ],
)
def test_jurisdiction_from_extent(extent: str | None, expected: str) -> None:
    assert jurisdiction_from_extent(extent) == expected


def test_jurisdiction_from_extent_unknown() -> None:
    with pytest.raises(ValueError):
        jurisdiction_from_extent("S")


def test_chunk_sha256_known_value() -> None:
    assert chunk_sha256(["A", "B"], "text") == chunk_sha256(["A", "B"], "text")
    assert chunk_sha256(["A", "B"], "text") != chunk_sha256(["A"], "B\n\ntext x")
    assert len(chunk_sha256([], "x")) == 64


def _chunk_data(**overrides: object) -> dict[str, object]:
    heading = ["Consumer Rights Act 2015", "Section 9"]
    text = "Goods to be of satisfactory quality."
    data: dict[str, object] = {
        "id": library_id(PATH, START),
        "source": "cra-2015",
        "source_url": "https://example.test/cra",
        "doc_type": "statute",
        "authority_tier": "statute",
        "jurisdiction": "uk",
        "extent": "E+W+S+N.I.",
        "heading_path": heading,
        "in_force_from": START,
        "in_force_to": None,
        "text_original": text,
        "text_contextual": None,
        "licence": "OGL v3.0",
        "attribution": "Contains public sector information",
        "source_sha256": "0" * 64,
        "chunk_sha256": chunk_sha256(heading, text),
    }
    data.update(overrides)
    return data


def test_law_chunk_valid_defaults() -> None:
    chunk = LawChunk(**_chunk_data())  # type: ignore[arg-type]
    assert chunk.topics == []
    assert chunk.holdout is False


def test_law_chunk_rejects_equal_end_date() -> None:
    with pytest.raises(ValidationError):
        LawChunk(**_chunk_data(in_force_to=START))  # type: ignore[arg-type]


def test_law_chunk_rejects_mismatched_id_date() -> None:
    bad_id = library_id(PATH, date(2016, 1, 1))
    with pytest.raises(ValidationError):
        LawChunk(**_chunk_data(id=bad_id))  # type: ignore[arg-type]


def test_law_chunk_rejects_wrong_hash() -> None:
    with pytest.raises(ValidationError):
        LawChunk(**_chunk_data(chunk_sha256="f" * 64))  # type: ignore[arg-type]


def test_stored_chunk_adds_optional_fields() -> None:
    chunk = StoredChunk(**_chunk_data())  # type: ignore[arg-type]
    assert chunk.embedding_model is None
    assert chunk.ingested_at is None


def test_search_filters_have_no_holdout_field() -> None:
    assert not [n for n in SearchFilters.model_fields if "holdout" in n]


def test_search_hit_rank_starts_at_one() -> None:
    SearchHit(chunk_id="x", score=0.5, rank=1, backend="memory")
    with pytest.raises(ValidationError):
        SearchHit(chunk_id="x", score=0.5, rank=0, backend="memory")
