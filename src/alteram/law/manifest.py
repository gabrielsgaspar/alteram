"""Law library manifest (design 6.6 step 5; docs/milestones/M3.md step 08).

Records what is in the library, where it came from and which models produced
it, so a rerun or a model change can be checked in code. The only I/O is
reading and writing the path given.
"""

import json
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ManifestError(ValueError):
    """The manifest file cannot be read as a manifest."""


class EmbeddingMismatch(ValueError):
    """Stored embeddings were made with another model or dimension."""


class SourceEntry(BaseModel):
    """One source in the library."""

    model_config = ConfigDict(frozen=True)

    source: str
    title: str
    licence: str
    attribution: str
    raw_files: dict[str, str]  # URL -> sha256
    version_dates: list[date]
    chunk_count: int
    unapplied_effects: dict[str, list[str]]  # provision URI path -> effects
    header_model: str | None
    header_prompt_version: int | None
    embedding_model: str | None
    embedding_dimension: int | None
    built_at: datetime
    notes: list[str] = Field(default_factory=list)


class Manifest(BaseModel):
    """All sources, keyed by source name."""

    model_config = ConfigDict(frozen=True)

    version: int = 1
    sources: dict[str, SourceEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _keys_match_sources(self) -> "Manifest":
        for key, entry in self.sources.items():
            if key != entry.source:
                raise ValueError(f"key {key!r} does not match source {entry.source!r}")
        return self


def read_manifest(path: Path) -> Manifest:
    """Read the manifest at `path`; a missing file gives an empty manifest."""
    if not path.exists():
        return Manifest()
    try:
        return Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise ManifestError(f"{path}: invalid manifest: {exc}") from exc


def write_manifest(path: Path, manifest: Manifest) -> None:
    """Write sorted, indented JSON so equal manifests give equal bytes."""
    text = json.dumps(
        manifest.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def check_embedding(manifest: Manifest, model: str, dimension: int) -> None:
    """Raise EmbeddingMismatch naming every source embedded with other settings."""
    bad = [
        f"{name}: {entry.embedding_model}/{entry.embedding_dimension}"
        for name, entry in sorted(manifest.sources.items())
        if (entry.embedding_model is not None and entry.embedding_model != model)
        or (
            entry.embedding_dimension is not None
            and entry.embedding_dimension != dimension
        )
    ]
    if bad:
        raise EmbeddingMismatch(
            f"configured {model}/{dimension}, but stored embeddings differ: "
            + "; ".join(bad)
        )


def update_source(manifest: Manifest, entry: SourceEntry) -> Manifest:
    """Return a new manifest with `entry` added or replacing its source."""
    return manifest.model_copy(
        update={"sources": {**manifest.sources, entry.source: entry}}
    )
