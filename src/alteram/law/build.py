"""Build step: raw legislation XML to a chunks JSONL file (M3.md 6.5).

No network and no model. Reads `raw_dir/<name>/fetch.json`, checks every file's
sha256, parses and merges the versions, and writes `out_dir/<name>.jsonl`.
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from alteram.law.chunk import SourceMeta, merge_versions, to_chunks
from alteram.law.fetch import SITE, Source
from alteram.law.legislation import parse_document
from alteram.law.models import LawChunk, Provision


class BuildError(ValueError):
    """The build cannot continue (unknown source, missing or altered file)."""


class BuildReport(BaseModel):
    chunk_count: int
    version_dates: list[date]
    skipped: dict[str, int]
    unapplied_effects: dict[str, list[str]]
    path: Path


def build_source(
    name: str, sources: Mapping[str, Source], raw_dir: Path, out_dir: Path
) -> BuildReport:
    """Turn the raw files of one legislation source into `out_dir/<name>.jsonl`."""
    source = sources.get(name)
    if source is None:
        raise BuildError(f"{name}: unknown source")
    if source.kind != "legislation":
        raise BuildError(f"{name}: cannot build a source of kind {source.kind!r}")

    source_dir = raw_dir / name
    manifest_path = source_dir / "fetch.json"
    if not manifest_path.is_file():
        raise BuildError(f"{name}: missing {manifest_path}")
    entries = sorted(json.loads(manifest_path.read_text()), key=lambda e: e["file"])

    provisions: list[Provision] = []
    sha_by_key: dict[tuple[str, date], str] = {}
    version_dates: set[date] = set()
    not_matching = 0
    for entry in entries:
        file = entry["file"]
        target = source_dir / file
        if not target.is_file():
            raise BuildError(f"{name}: file {file} is listed in fetch.json but missing")
        data = target.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"]:
            raise BuildError(f"{name}: file {file} does not match its sha256")
        try:
            parsed = parse_document(data, name)
        except ValueError as exc:
            raise BuildError(f"{name}: file {file}: {exc}") from exc
        version_dates.add(parsed.valid_from)
        not_matching += parsed.skipped
        for p in parsed.provisions:
            sha_by_key.setdefault((p.uri_path, p.in_force_from), digest)
        provisions.extend(parsed.provisions)

    effects: dict[str, set[str]] = {}
    for p in provisions:
        if p.unapplied_effects:
            effects.setdefault(p.uri_path, set()).update(p.unapplied_effects)

    meta = SourceMeta(
        source=name,
        source_url_base=SITE,
        doc_type=source.doc_type,  # type: ignore[arg-type]
        authority_tier=source.authority_tier,  # type: ignore[arg-type]
        licence=source.licence,
        attribution=source.attribution,
        topics_by_section=source.topics,
    )
    prospective = sum(1 for p in provisions if p.status == "prospective")
    chunks = to_chunks(merge_versions(provisions), meta, sha_by_key)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.jsonl"
    path.write_bytes(
        "".join(c.model_dump_json() + "\n" for c in chunks).encode("utf-8")
    )
    return BuildReport(
        chunk_count=len(chunks),
        version_dates=sorted(version_dates),
        skipped={"not_matching": not_matching, "prospective": prospective},
        unapplied_effects={k: sorted(v) for k, v in sorted(effects.items())},
        path=path,
    )


def read_chunks(path: Path) -> list[LawChunk]:
    """Read a chunks JSONL file written by `build_source`."""
    return [
        LawChunk.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
