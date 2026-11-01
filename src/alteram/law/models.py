"""Law library data models and pure helpers (docs/milestones/M3.md 6.1 to 6.4).

No I/O happens here. Later steps (parser, chunker, store, loader) share these
definitions of a provision, a chunk, a library ID and "in force on a date".
"""

import hashlib
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

DocType = Literal["statute", "regulation", "decision", "case_law", "guidance"]
AuthorityTier = Literal["statute", "regulation", "decision", "case_law", "guidance"]
Status = Literal["in_force", "prospective", "repealed"]
Backend = Literal["memory", "postgres_fts", "pgvector"]

_JURISDICTIONS: dict[str | None, str] = {
    "E+W+S+N.I.": "uk",
    "E+W": "england_wales",
    "E+W+S": "great_britain",
    None: "unknown",
}


def chunk_sha256(heading_path: list[str], text: str) -> str:
    """Hash of the heading path (joined by newlines), a blank line, then the text."""
    payload = "\n".join(heading_path) + "\n\n" + text
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# The LawChunk field of the same name shadows the function inside the class body.
_chunk_hash = chunk_sha256


def library_id(uri_path: str, in_force_from: date, part: int | None = None) -> str:
    """Build `<uri_path>/<YYYY-MM-DD>`, plus `~<part>` for a split provision."""
    if not uri_path or uri_path.endswith("/"):
        raise ValueError(f"invalid uri_path: {uri_path!r}")
    if part is not None and part < 1:
        raise ValueError(f"part must be 1 or more, got {part}")
    result = f"{uri_path}/{in_force_from.isoformat()}"
    return result if part is None else f"{result}~{part}"


def _check_uri_path(uri_path: str) -> None:
    """Shape check only: no empty segments; FCA is `fca/<SOURCEBOOK>/<rule>`.

    Legislation paths need at least three segments (`<type>/<year>/<number>`).
    Deeper structure is not checked so real paths such as schedules still pass.
    """
    segments = uri_path.split("/")
    if any(not s for s in segments):
        raise ValueError(f"empty segment in uri_path: {uri_path!r}")
    if segments[0] == "fca":
        if len(segments) != 3:
            raise ValueError(f"FCA ID must be fca/<SOURCEBOOK>/<rule>: {uri_path!r}")
    elif len(segments) < 3:
        raise ValueError(f"uri_path too short: {uri_path!r}")


def parse_library_id(id: str) -> tuple[str, date, int | None]:
    """Split a library ID into (uri_path, in_force_from, part). Raises ValueError."""
    uri_path, sep, tail = id.rpartition("/")
    if not sep:
        raise ValueError(f"library ID has no date: {id!r}")
    date_text, tilde, part_text = tail.partition("~")
    part: int | None = None
    if tilde:
        if not part_text.isascii() or not part_text.isdigit() or int(part_text) < 1:
            raise ValueError(f"invalid part in library ID: {id!r}")
        part = int(part_text)
    try:
        if len(date_text) != 10:
            raise ValueError
        in_force_from = date.fromisoformat(date_text)
    except ValueError:
        raise ValueError(f"invalid date in library ID: {id!r}") from None
    _check_uri_path(uri_path)
    return uri_path, in_force_from, part


class _HasValidity(Protocol):
    @property
    def in_force_from(self) -> date: ...
    @property
    def in_force_to(self) -> date | None: ...


def in_force_on(obj: _HasValidity, as_of: date) -> bool:
    """Half-open validity: from <= as_of < to, with no end meaning open-ended."""
    return obj.in_force_from <= as_of and (
        obj.in_force_to is None or as_of < obj.in_force_to
    )


def jurisdiction_from_extent(extent: str | None) -> str:
    """Map a raw RestrictExtent value to a jurisdiction name."""
    try:
        return _JURISDICTIONS[extent]
    except KeyError:
        raise ValueError(f"unknown extent: {extent!r}") from None


class Provision(BaseModel):
    """One provision as parsed from a source, before chunking."""

    source: str
    uri_path: str
    heading_path: list[str]
    number: str
    text: str
    extent: str | None
    in_force_from: date
    in_force_to: date | None
    status: Status
    unapplied_effects: list[str]
    authority_tier: AuthorityTier | None = None


class LawChunk(BaseModel):
    """A row of `law_chunks` without the embedding, ingestion and search columns."""

    id: str
    source: str
    source_url: str
    doc_type: DocType
    authority_tier: AuthorityTier
    jurisdiction: str
    extent: str | None
    heading_path: list[str]
    in_force_from: date
    in_force_to: date | None
    text_original: str
    text_contextual: str | None
    topics: list[str] = Field(default_factory=list)
    holdout: bool = False
    licence: str
    attribution: str
    source_sha256: str
    chunk_sha256: str

    @model_validator(mode="after")
    def _check_consistency(self) -> "LawChunk":
        if self.in_force_to is not None and self.in_force_to <= self.in_force_from:
            raise ValueError("in_force_to must be after in_force_from")
        id_date = parse_library_id(self.id)[1]
        if id_date != self.in_force_from:
            raise ValueError("date in id must equal in_force_from")
        expected = _chunk_hash(self.heading_path, self.text_original)
        if self.chunk_sha256 != expected:
            raise ValueError(
                "chunk_sha256 does not match heading_path and text_original"
            )
        return self


class StoredChunk(LawChunk):
    """A chunk as held by a store."""

    embedding_model: str | None = None
    ingested_at: datetime | None = None


class SearchFilters(BaseModel):
    """Search filters. There is deliberately no way to ask for holdout rows."""

    model_config = ConfigDict(frozen=True)

    doc_types: frozenset[str] | None = None
    jurisdictions: frozenset[str] | None = None
    sources: frozenset[str] | None = None
    topics: frozenset[str] | None = None


class SearchHit(BaseModel):
    """One search result."""

    chunk_id: str
    score: float
    rank: int = Field(ge=1)
    backend: Backend
