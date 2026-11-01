"""Merge dated versions into validity spans and build chunks (M3.md 6.2, 6.5).

Pure functions, no I/O. `merge_versions` turns the provisions parsed from several
point-in-time versions into one provision per distinct text per validity span.
`to_chunks` expects that merged list.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date

from pydantic import BaseModel

from alteram.law.models import (
    AuthorityTier,
    DocType,
    LawChunk,
    Provision,
    chunk_sha256,
    jurisdiction_from_extent,
    library_id,
)


class SourceMeta(BaseModel):
    """Per-source facts that every chunk of the source shares."""

    source: str
    source_url_base: str
    doc_type: DocType
    authority_tier: AuthorityTier
    licence: str
    attribution: str
    topics_by_section: dict[str, list[str]] = {}


def merge_versions(provisions: Iterable[Provision]) -> list[Provision]:
    """Join identical consecutive texts into spans; see the module docstring.

    Version dates are the distinct `in_force_from` values in the input. A
    provision absent from a later version ends at that version's date.
    """
    items = [p for p in provisions if p.status != "prospective"]
    version_dates = sorted({p.in_force_from for p in items})
    groups: dict[str, list[Provision]] = defaultdict(list)
    for p in items:
        groups[p.uri_path].append(p)
    spans: list[Provision] = []
    for uri_path in sorted(groups):
        group = sorted(groups[uri_path], key=lambda p: (p.in_force_from, p.text))
        spans.extend(_merge_group(uri_path, group, version_dates))
    return sorted(spans, key=lambda p: (p.uri_path, p.in_force_from))


def _merge_group(
    uri_path: str, group: list[Provision], version_dates: list[date]
) -> list[Provision]:
    spans: list[Provision] = []
    current: Provision | None = None
    last_seen: date | None = None
    for p in group:
        if last_seen == p.in_force_from and current and p.text != current.text:
            raise ValueError(f"{uri_path}: different texts from {p.in_force_from}")
        last_seen = p.in_force_from
        if p.status == "repealed":
            if current is not None:
                spans.append(_close(current, p.in_force_from))
                current = None
        elif current is not None and p.text == current.text:
            if p.in_force_to is not None:
                current = current.model_copy(update={"in_force_to": p.in_force_to})
        else:
            if current is not None:
                spans.append(_close(current, p.in_force_from))
            current = p
    if current is not None and last_seen is not None:
        later = [d for d in version_dates if d > last_seen]
        spans.append(_close(current, later[0] if later else None))
    _check_overlaps(uri_path, spans)
    return spans


def _close(span: Provision, end: date | None) -> Provision:
    """End a span at `end` unless the parser gave an explicit end (that wins)."""
    if span.in_force_to is not None or end is None:
        return span
    return span.model_copy(update={"in_force_to": end})


def _check_overlaps(uri_path: str, spans: list[Provision]) -> None:
    for a, b in zip(spans, spans[1:], strict=False):
        if a.in_force_to is not None and a.in_force_to > b.in_force_from:
            raise ValueError(
                f"{uri_path}: overlapping spans with different text "
                f"({a.in_force_from} to {a.in_force_to} and from {b.in_force_from})"
            )


def split_text(text: str, limit: int = 4000, heading: str = "") -> list[str]:
    """Split at paragraph, then line, then sentence boundaries; never over `limit`.

    Parts after the first start with `[<heading>]` on its own line, and that
    prefix counts toward the limit.
    """
    if len(text) <= limit:
        return [text]
    prefix = f"[{heading}]\n" if heading else ""
    room = limit - len(prefix)
    if room < 1:
        raise ValueError("heading is too long for the limit")
    parts: list[str] = []
    body = ""
    for sep, atom in _atoms(text, room):
        budget = room if parts else limit
        if body and len(body) + len(sep) + len(atom) <= budget:
            body += sep + atom
        elif not body and len(atom) <= budget:
            body = atom
        else:
            parts.append(body)
            body = atom
    parts.append(body)
    return [parts[0], *(prefix + part for part in parts[1:])]


def _atoms(text: str, room: int) -> list[tuple[str, str]]:
    """Pieces of the text, each with the separator that precedes it."""
    atoms: list[tuple[str, str]] = []
    for i, paragraph in enumerate(text.split("\n\n")):
        para_sep = "\n\n" if i else ""
        if len(paragraph) <= room:
            atoms.append((para_sep, paragraph))
            continue
        for j, line in enumerate(paragraph.split("\n")):
            sep = para_sep if j == 0 else "\n"
            if len(line) <= room:
                atoms.append((sep, line))
                continue
            for k, (piece_sep, piece) in enumerate(_split_line(line, room)):
                atoms.append((sep if k == 0 else piece_sep, piece))
    return atoms


def _split_line(line: str, room: int) -> list[tuple[str, str]]:
    """Split one long line at the last sentence end that fits, else hard split."""
    pieces: list[tuple[str, str]] = []
    sep = ""
    while len(line) > room:
        idx = line.rfind(". ", 0, room)
        if idx > 0:
            pieces.append((sep, line[: idx + 1]))
            line = line[idx + 2 :]
            sep = " "
        else:
            pieces.append((sep, line[:room]))
            line = line[room:]
            sep = ""
    if line:
        pieces.append((sep, line))
    return pieces


def to_chunks(
    provisions: Iterable[Provision],
    source_meta: SourceMeta,
    source_sha256: Mapping[tuple[str, date], str],
) -> list[LawChunk]:
    """Build chunks from merged provisions, sorted by ID.

    `source_sha256` is keyed by (uri_path, in_force_from) of each provision.
    """
    chunks: list[LawChunk] = []
    for p in provisions:
        parts = split_text(p.text, heading=p.heading_path[-1] if p.heading_path else "")
        for n, part in enumerate(parts, start=1):
            chunks.append(
                LawChunk(
                    id=library_id(
                        p.uri_path, p.in_force_from, n if len(parts) > 1 else None
                    ),
                    source=source_meta.source,
                    source_url=_source_url(source_meta, p),
                    doc_type=source_meta.doc_type,
                    authority_tier=p.authority_tier or source_meta.authority_tier,
                    jurisdiction=jurisdiction_from_extent(p.extent),
                    extent=p.extent,
                    heading_path=p.heading_path,
                    in_force_from=p.in_force_from,
                    in_force_to=p.in_force_to,
                    text_original=part,
                    text_contextual=None,
                    topics=list(
                        source_meta.topics_by_section.get(_section(p.uri_path), [])
                    ),
                    licence=source_meta.licence,
                    attribution=source_meta.attribution,
                    source_sha256=source_sha256[(p.uri_path, p.in_force_from)],
                    chunk_sha256=chunk_sha256(p.heading_path, part),
                )
            )
    return sorted(chunks, key=lambda c: c.id)


def _source_url(meta: SourceMeta, p: Provision) -> str:
    base = meta.source_url_base.rstrip("/")
    return f"{base}/{p.uri_path}/{p.in_force_from.isoformat()}"


def _section(uri_path: str) -> str:
    """The segment after `section/` in a path, or an empty string."""
    segments = uri_path.split("/")
    if "section" in segments:
        i = segments.index("section")
        if i + 1 < len(segments):
            return segments[i + 1]
    return ""
