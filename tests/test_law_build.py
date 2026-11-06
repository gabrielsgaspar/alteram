"""Tests for the build step, on the fixtures in tests/fixtures/law/legislation."""

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from alteram.law.build import BuildError, build_source, read_chunks
from alteram.law.fetch import Source
from alteram.law.legislation import parse_document
from alteram.law.models import LawChunk, in_force_on

FIXTURES = Path(__file__).parent / "fixtures" / "law" / "legislation"
S88 = [
    "ukpga-1974-39-section-88@2006-06-16.xml",
    "ukpga-1974-39-section-88@2006-10-01.xml",
    "ukpga-1974-39-section-88@2008-10-01.xml",
    "ukpga-1974-39-section-88@current.xml",
]
S140A = "ukpga-1974-39-section-140A@1990-01-01.xml"
CRA_S12 = "ukpga-2015-15-section-12@current.xml"
TODAY = date(2026, 11, 6)


def make_source(kind: str = "legislation") -> Source:
    return Source(
        kind=kind,  # type: ignore[arg-type]
        base="ukpga/1974/39",
        title="Test",
        sections=["88"],
        doc_type="statute",
        authority_tier="statute",
        licence="OGL",
        attribution="Contains public sector information",
        topics={"88": ["default"]},
    )


def prepare(tmp_path: Path, files: list[str], name: str = "cca") -> Path:
    """Copy fixtures into `raw/<name>` and write a fetch.json for them."""
    raw = tmp_path / "raw"
    target = raw / name
    target.mkdir(parents=True)
    entries = []
    for file in files:
        shutil.copy(FIXTURES / file, target / file)
        entries.append(
            {
                "file": file,
                "sha256": hashlib.sha256((FIXTURES / file).read_bytes()).hexdigest(),
                "url": "https://example.invalid/" + file,
                "fetched_at": "2026-11-06T00:00:00+00:00",
            }
        )
    (target / "fetch.json").write_text(json.dumps(entries))
    return raw


def build(tmp_path: Path, files: list[str], name: str = "cca"):
    raw = prepare(tmp_path, files, name)
    return build_source(name, {name: make_source()}, raw, tmp_path / "out")


def expected_spans() -> dict[str, list[date]]:
    """Start dates of each subsection's spans, from the dated fixture texts."""
    dated = [f for f in S88 if "current" not in f]
    texts: dict[str, dict[date, str]] = {}
    for file in dated:
        doc = parse_document((FIXTURES / file).read_bytes(), "x")
        for p in doc.provisions:
            texts.setdefault(p.uri_path, {})[p.in_force_from] = p.text
    starts: dict[str, list[date]] = {}
    for uri_path, by_date in texts.items():
        previous = None
        for start in sorted(by_date):
            if by_date[start] != previous:
                starts.setdefault(uri_path, []).append(start)
            previous = by_date[start]
    return starts


def s88_chunks(tmp_path: Path) -> list[LawChunk]:
    report = build(tmp_path, [*S88, S140A])
    return read_chunks(report.path)


def test_s88_spans_match_fixture_texts(tmp_path: Path) -> None:
    chunks = s88_chunks(tmp_path)
    expected = expected_spans()
    assert expected
    for uri_path, starts in expected.items():
        actual = sorted(
            c.in_force_from for c in chunks if c.id.rsplit("/", 1)[0] == uri_path
        )
        assert actual == starts, uri_path
    by_suffix = {path.rsplit("/", 1)[-1]: starts for path, starts in expected.items()}
    assert len(by_suffix["1"]) == 1
    assert by_suffix["2"][-1] == date(2006, 10, 1)
    assert by_suffix["4A"] == [date(2008, 10, 1)]


def test_s88_subsections_each_have_one_open_chunk_in_force_today(
    tmp_path: Path,
) -> None:
    chunks = s88_chunks(tmp_path)
    for number in ("1", "2", "3", "4", "4A", "5"):
        mine = [
            c for c in chunks if c.id.split("/section/88/")[-1].startswith(f"{number}/")
        ]
        assert mine, number
        open_ended = [c for c in mine if c.in_force_to is None]
        assert len(open_ended) == 1, number
        assert [c for c in mine if in_force_on(c, TODAY)] == open_ended
    # The 2006-10-01 wording is the one in force for (2) and (3).
    for number in ("2", "3"):
        current = next(
            c
            for c in chunks
            if c.id.split("/section/88/")[-1].startswith(f"{number}/")
            and c.in_force_to is None
        )
        assert current.in_force_from == date(2006, 10, 1)


def test_every_line_validates_as_a_chunk(tmp_path: Path) -> None:
    report = build(tmp_path, [*S88, S140A])
    lines = report.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == report.chunk_count > 0
    for line in lines:
        LawChunk.model_validate_json(line)
    assert report.path.read_bytes().endswith(b"\n")
    ids = [json.loads(line)["id"] for line in lines]
    assert ids == sorted(ids)


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    first = build(tmp_path / "a", [*S88, S140A])
    second = build(tmp_path / "b", [*S88, S140A])
    assert first.path.read_bytes() == second.path.read_bytes()


def test_tampered_file_stops_the_build_and_is_named(tmp_path: Path) -> None:
    raw = prepare(tmp_path, S88)
    victim = raw / "cca" / S88[1]
    data = bytearray(victim.read_bytes())
    data[-5] ^= 1
    victim.write_bytes(bytes(data))
    with pytest.raises(BuildError, match=S88[1]):
        build_source("cca", {"cca": make_source()}, raw, tmp_path / "out")


def test_missing_file_is_named(tmp_path: Path) -> None:
    raw = prepare(tmp_path, S88)
    (raw / "cca" / S88[0]).unlink()
    with pytest.raises(BuildError, match=S88[0]):
        build_source("cca", {"cca": make_source()}, raw, tmp_path / "out")


def test_read_chunks_returns_what_was_written(tmp_path: Path) -> None:
    report = build(tmp_path, [*S88, S140A])
    chunks = read_chunks(report.path)
    assert len(chunks) == report.chunk_count
    rewritten = "".join(c.model_dump_json() + "\n" for c in chunks)
    assert rewritten.encode("utf-8") == report.path.read_bytes()


def test_report_lists_cra_s12_effect(tmp_path: Path) -> None:
    report = build(tmp_path, [CRA_S12], name="cra")
    assert report.unapplied_effects
    for uri_path, effects in report.unapplied_effects.items():
        assert uri_path.startswith("ukpga/2015/15/section/12")
        assert effects == sorted(set(effects)) and effects
    all_effects = [e for es in report.unapplied_effects.values() for e in es]
    assert any("s. 12(3)" in e for e in all_effects)


def test_report_counts_skipped_and_version_dates(tmp_path: Path) -> None:
    report = build(tmp_path, [*S88, S140A])
    assert report.skipped["not_matching"] >= 5
    assert report.skipped["prospective"] == 0
    assert report.version_dates == sorted(set(report.version_dates))
    assert date(1991, 2, 1) in report.version_dates


def test_unknown_source_raises(tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="nope"):
        build_source("nope", {}, tmp_path, tmp_path / "out")


def test_fca_source_raises(tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="fca"):
        build_source("fca", {"fca": make_source("fca")}, tmp_path, tmp_path / "out")
