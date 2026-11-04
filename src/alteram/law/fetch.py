"""Fetch point-in-time versions of listed sections from legislation.gov.uk."""

import hashlib
import importlib.metadata
import json
import os
import tomllib
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from alteram.law.legislation import parse_document

SITE = "https://www.legislation.gov.uk"
PAUSE_SECONDS = 1.0


class FetchError(RuntimeError):
    """A download failed."""


class Source(BaseModel, extra="forbid"):
    kind: Literal["legislation", "fca"]
    base: str
    title: str
    sections: list[str]
    doc_type: str
    authority_tier: str
    licence: str
    attribution: str
    topics: dict[str, list[str]] = {}


class FetchReport(BaseModel):
    fetched: int = 0
    skipped: int = 0
    files: list[str] = []


def load_sources(path: str | Path) -> dict[str, Source]:
    """Read and validate the sources file. Errors start with the source name."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    sources: dict[str, Source] = {}
    for name, entry in raw.items():
        try:
            sources[name] = Source.model_validate(entry)
        except ValidationError as err:
            problems = "; ".join(
                ".".join(str(p) for p in e["loc"]) + ": " + e["msg"]
                for e in err.errors()
            )
            raise ValueError(name + ": " + problems) from err
    return sources


def section_url(base: str, section: str, version: date | None = None) -> str:
    middle = "/" + version.isoformat() if version else ""
    return SITE + "/" + base + "/section/" + section + middle + "/data.xml"


def _write_atomic(target: Path, data: bytes) -> None:
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def fetch_source(
    source: Source,
    raw_dir: Path,
    client: httpx.Client,
    sleep: Callable[[float], None],
    now: datetime,
    contact: str,
    refresh: bool = False,
    *,
    name: str,
) -> FetchReport:
    """Download the current and every dated version of each section.

    Files go to `raw_dir/<name>/<section>@<date|current>.xml`. Existing files are
    skipped unless `refresh`. `fetch.json` lists every file with its sha256.
    """
    if not contact.strip():
        raise ValueError(
            "contact is required for the User-Agent (ALTERAM_HTTP_CONTACT)"
        )
    version_text = importlib.metadata.version("alteram")
    headers = {"User-Agent": "alteram/" + version_text + " (+" + contact + ")"}
    out_dir = raw_dir / name
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "fetch.json"
    entries: dict[str, dict[str, str]] = {}
    if manifest_path.exists():
        entries = {e["file"]: e for e in json.loads(manifest_path.read_text())}

    report = FetchReport()
    requests_made = 0

    def get(section: str, version: date | None) -> bytes:
        nonlocal requests_made
        label = version.isoformat() if version else "current"
        file = section + "@" + label + ".xml"
        target = out_dir / file
        if target.exists() and not refresh:
            report.skipped += 1
            return target.read_bytes()
        url = section_url(source.base, section, version)
        if requests_made:
            sleep(PAUSE_SECONDS)
        requests_made += 1
        response = client.get(url, headers=headers)
        if response.status_code != 200:
            raise FetchError(url + ": HTTP " + str(response.status_code))
        data = response.content
        _write_atomic(target, data)
        entries[file] = {
            "url": url,
            "file": file,
            "sha256": hashlib.sha256(data).hexdigest(),
            "fetched_at": now.isoformat(),
        }
        report.fetched += 1
        report.files.append(file)
        return data

    try:
        for section in source.sections:
            current = get(section, None)
            parsed = parse_document(current, name + " s." + section)
            for version in parsed.version_dates:
                get(section, version)
    finally:
        # Record what was fetched even if a later request failed.
        ordered = [entries[k] for k in sorted(entries)]
        manifest_path.write_text(json.dumps(ordered, indent=2, sort_keys=True) + "\n")
    return report
