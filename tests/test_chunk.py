import random
from datetime import date
from pathlib import Path

import pytest

from alteram.law.chunk import SourceMeta, merge_versions, split_text, to_chunks
from alteram.law.legislation import parse_document
from alteram.law.models import Provision, in_force_on, parse_library_id

URI = "ukpga/2015/15/section/22"
D1, D2, D3 = date(2015, 10, 1), date(2018, 1, 1), date(2022, 6, 1)


def prov(
    text: str,
    start: date,
    uri: str = URI,
    status: str = "in_force",
    end: date | None = None,
    **kw,
) -> Provision:
    return Provision(
        source="cra",
        uri_path=uri,
        heading_path=["Part 1", "s.22 Time limit for short-term right to reject"],
        number="22",
        text=text,
        extent="E+W+S+N.I.",
        in_force_from=start,
        in_force_to=end,
        status=status,
        unapplied_effects=[],
        **kw,
    )


META = SourceMeta(
    source="cra",
    source_url_base="https://www.legislation.gov.uk",
    doc_type="statute",
    authority_tier="statute",
    licence="OGL",
    attribution="Contains public sector information",
    topics_by_section={"22": ["consumer"]},
)


def shas(provs: list[Provision]) -> dict[tuple[str, date], str]:
    return {(p.uri_path, p.in_force_from): "abc" for p in provs}


def test_identical_versions_join_and_change_starts_new_span() -> None:
    out = merge_versions([prov("a", D1), prov("a", D2), prov("b", D3)])
    assert [(p.text, p.in_force_from, p.in_force_to) for p in out] == [
        ("a", D1, D3),
        ("b", D3, None),
    ]


def test_absent_from_later_version_of_same_section_ends_span() -> None:
    sub1, sub2 = f"{URI}/1", f"{URI}/2"
    other = prov("x", D3, uri=sub2)
    out = merge_versions([prov("a", D1, uri=sub1), prov("a", D2, uri=sub1), other])
    first = [p for p in out if p.uri_path == sub1]
    assert [(p.in_force_from, p.in_force_to) for p in first] == [(D1, D3)]


def test_later_version_of_other_section_does_not_end_span() -> None:
    other = prov("x", D3, uri="ukpga/2015/15/section/23")
    out = merge_versions([prov("a", D1), prov("a", D2), other])
    first = [p for p in out if p.uri_path == URI]
    assert [(p.in_force_from, p.in_force_to) for p in first] == [(D1, None)]


def test_later_open_ended_version_with_same_text_reopens_span() -> None:
    out = merge_versions([prov("a", D1, end=D2), prov("a", D2, end=D3), prov("a", D3)])
    assert [(p.in_force_from, p.in_force_to) for p in out] == [(D1, None)]


def test_absent_then_back_starts_new_span() -> None:
    sub1, sub2 = f"{URI}/1", f"{URI}/2"
    provs = [prov("a", D1, uri=sub1), prov("x", D2, uri=sub2), prov("a", D3, uri=sub1)]
    out = [p for p in merge_versions(provs) if p.uri_path == sub1]
    assert [(p.in_force_from, p.in_force_to) for p in out] == [(D1, D2), (D3, None)]


def test_repealed_version_ends_span() -> None:
    out = merge_versions(
        [prov("a", D1), prov("a", D2), prov("", D3, status="repealed")]
    )
    assert [(p.in_force_from, p.in_force_to) for p in out] == [(D1, D3)]


def test_prospective_dropped() -> None:
    out = merge_versions([prov("a", D1), prov("b", D2, status="prospective")])
    assert [(p.text, p.in_force_to) for p in out] == [("a", None)]


def test_explicit_end_wins() -> None:
    explicit = date(2016, 1, 1)
    out = merge_versions([prov("a", D1, end=explicit), prov("b", D3)])
    assert out[0].in_force_to == explicit


def test_overlap_with_different_text_raises() -> None:
    with pytest.raises(ValueError, match=URI):
        merge_versions([prov("a", D1, end=date(2020, 1, 1)), prov("b", D2)])


def test_same_date_different_text_raises() -> None:
    with pytest.raises(ValueError, match=URI):
        merge_versions([prov("a", D1), prov("b", D1)])


def test_inputs_not_mutated() -> None:
    p = prov("a", D1)
    merge_versions([p, prov("b", D2)])
    assert p.in_force_to is None


def test_split_short_text_unchanged() -> None:
    assert split_text("short", limit=100) == ["short"]


def test_split_respects_limit_and_lines() -> None:
    lines = [f"line {i} " + "x" * 20 for i in range(30)]
    text = "\n".join(lines)
    parts = split_text(text, limit=200, heading="H")
    assert len(parts) > 1
    assert all(len(p) <= 200 for p in parts)
    seen = [ln for p in parts for ln in p.split("\n") if not ln.startswith("[H]")]
    assert seen == lines


def test_split_prefixes_later_parts_with_heading() -> None:
    text = "\n\n".join("para " + "y" * 50 for _ in range(10))
    parts = split_text(text, limit=150, heading="s.22 Time limit")
    assert not parts[0].startswith("[")
    assert all(p.startswith("[s.22 Time limit]\n") for p in parts[1:])


def test_split_long_line_at_sentence_end() -> None:
    text = "First sentence here. Second sentence here. Third sentence here."
    parts = split_text(text, limit=45)
    assert parts[0] == "First sentence here. Second sentence here."
    assert all(len(p) <= 45 for p in parts)


def test_split_hard_when_no_sentence_end() -> None:
    parts = split_text("z" * 250, limit=100)
    assert all(len(p) <= 100 for p in parts)
    assert "".join(parts) == "z" * 250


def test_to_chunks_ids_round_trip_and_suffixes() -> None:
    long = prov("\n".join("w" * 100 for _ in range(100)), D1)
    short = prov("short", D1, uri="ukpga/2015/15/section/23")
    chunks = to_chunks([long, short], META, shas([long, short]))
    for c in chunks:
        parse_library_id(c.id)
    ids = [c.id for c in chunks]
    assert f"{URI}/2015-10-01~1" in ids and f"{URI}/2015-10-01~2" in ids
    assert "ukpga/2015/15/section/23/2015-10-01" in ids
    assert all(parse_library_id(i)[2] is None for i in ids if "section/23" in i)


def test_to_chunks_fields() -> None:
    p = prov("a", D1, authority_tier="regulation")
    (c,) = to_chunks([p], META, shas([p]))
    assert c.authority_tier == "regulation"
    assert c.jurisdiction == "uk"
    assert c.topics == ["consumer"]
    assert c.source_url == f"https://www.legislation.gov.uk/{URI}/2015-10-01"
    assert c.source_sha256 == "abc"
    assert c.text_contextual is None


def test_to_chunks_default_tier_and_no_topics() -> None:
    p = prov("a", D1, uri="ukpga/2015/15/section/99")
    (c,) = to_chunks([p], META, shas([p]))
    assert c.authority_tier == "statute"
    assert c.topics == []


def test_order_is_deterministic() -> None:
    other = "ukpga/2015/15/section/23"
    provs = [
        prov("a", D1),
        prov("a", D2),
        prov("b", D3),
        prov("c", D1, uri=other),
        prov("d", D2, uri=other),
    ]
    expected = merge_versions(provs)
    expected_chunks = to_chunks(expected, META, shas(provs))
    for seed in range(5):
        shuffled = provs[:]
        random.Random(seed).shuffle(shuffled)
        merged = merge_versions(shuffled)
        assert merged == expected
        assert to_chunks(merged, META, shas(provs)) == expected_chunks


FIXTURES = Path(__file__).parent / "fixtures" / "law" / "legislation"
S88 = "ukpga/1974/39/section/88"
S88_SPANS = {
    f"{S88}/1": [(date(2006, 6, 16), None)],
    f"{S88}/2": [(date(2006, 6, 16), date(2006, 10, 1)), (date(2006, 10, 1), None)],
    f"{S88}/3": [(date(2006, 6, 16), date(2006, 10, 1)), (date(2006, 10, 1), None)],
    f"{S88}/4": [(date(2006, 6, 16), None)],
    f"{S88}/4A": [(date(2008, 10, 1), None)],
    f"{S88}/5": [(date(2006, 6, 16), None)],
}


def parse_fixtures(pattern: str) -> list[Provision]:
    return [
        p
        for f in sorted(FIXTURES.glob(pattern))
        for p in parse_document(f.read_bytes(), "cca").provisions
    ]


def s88_spans(merged: list[Provision]) -> dict[str, list[tuple[date, date | None]]]:
    spans: dict[str, list[tuple[date, date | None]]] = {}
    for p in merged:
        if p.uri_path.startswith(f"{S88}/"):
            spans.setdefault(p.uri_path, []).append((p.in_force_from, p.in_force_to))
    return spans


def test_s88_fixture_spans() -> None:
    merged = merge_versions(parse_fixtures("ukpga-1974-39-section-88@*.xml"))
    assert s88_spans(merged) == S88_SPANS


def test_s88_spans_unchanged_when_all_fixtures_merged() -> None:
    merged = merge_versions(parse_fixtures("*.xml"))
    assert s88_spans(merged) == S88_SPANS


def test_s88_one_span_in_force_per_subsection() -> None:
    merged = merge_versions(parse_fixtures("*.xml"))
    as_of = date(2026, 11, 1)
    for uri_path in S88_SPANS:
        live = [p for p in merged if p.uri_path == uri_path and in_force_on(p, as_of)]
        assert len(live) == 1, uri_path
