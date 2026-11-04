from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from alteram.law.manifest import (
    EmbeddingMismatch,
    Manifest,
    ManifestError,
    SourceEntry,
    check_embedding,
    read_manifest,
    update_source,
    write_manifest,
)


def entry(name: str, **kw: object) -> SourceEntry:
    data: dict[str, object] = {
        "source": name,
        "title": f"Title {name}",
        "licence": "OGL",
        "attribution": "Crown",
        "raw_files": {"https://b.example/x": "bb", "https://a.example/x": "aa"},
        "version_dates": [date(2020, 1, 1), date(2021, 6, 1)],
        "chunk_count": 3,
        "unapplied_effects": {"/ukpga/1/2": ["repealed"], "/ukpga/1/1": ["amended"]},
        "header_model": "h",
        "header_prompt_version": 1,
        "embedding_model": "m",
        "embedding_dimension": 8,
        "built_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    }
    data.update(kw)
    return SourceEntry(**data)  # type: ignore[arg-type]


def two() -> Manifest:
    return Manifest(sources={"a": entry("a"), "b": entry("b", notes=["n"])})


def test_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "law" / "manifest.json"
    write_manifest(p, two())
    assert read_manifest(p) == two()


def test_bytes_stable(tmp_path: Path) -> None:
    p1, p2 = tmp_path / "1.json", tmp_path / "2.json"
    write_manifest(p1, two())
    write_manifest(
        p2, Manifest(sources={"b": entry("b", notes=["n"]), "a": entry("a")})
    )
    assert p1.read_bytes() == p2.read_bytes()
    assert p1.read_bytes().endswith(b"}\n")
    assert b'"2020-01-01"' in p1.read_bytes()


def test_check_embedding_passes() -> None:
    check_embedding(two(), "m", 8)
    check_embedding(Manifest(), "x", 1)
    bare = entry("c", embedding_model=None, embedding_dimension=None)
    check_embedding(Manifest(sources={"c": bare}), "x", 1)


def test_check_embedding_model_mismatch() -> None:
    with pytest.raises(EmbeddingMismatch, match="a: m/8"):
        check_embedding(Manifest(sources={"a": entry("a")}), "other", 8)


def test_check_embedding_dimension_mismatch() -> None:
    with pytest.raises(EmbeddingMismatch, match="a: m/8"):
        check_embedding(Manifest(sources={"a": entry("a")}), "m", 16)


def test_check_embedding_names_every_source() -> None:
    with pytest.raises(EmbeddingMismatch) as exc:
        check_embedding(two(), "other", 16)
    assert "a: m/8" in str(exc.value)
    assert "b: m/8" in str(exc.value)


def test_missing_path_is_empty(tmp_path: Path) -> None:
    assert read_manifest(tmp_path / "none.json").sources == {}


def test_malformed_json_names_path(tmp_path: Path) -> None:
    p = tmp_path / "m.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError, match="m.json"):
        read_manifest(p)


def test_wrong_shape_names_path(tmp_path: Path) -> None:
    p = tmp_path / "m.json"
    p.write_text('{"sources": []}', encoding="utf-8")
    with pytest.raises(ManifestError, match="m.json"):
        read_manifest(p)


def test_update_source_replaces_and_adds() -> None:
    m = two()
    replaced = update_source(m, entry("a", chunk_count=9))
    assert replaced.sources["a"].chunk_count == 9
    added = update_source(m, entry("c"))
    assert set(added.sources) == {"a", "b", "c"}
    assert m == two()


def test_key_must_match_source() -> None:
    with pytest.raises(ValueError, match="does not match"):
        Manifest(sources={"x": entry("a")})
