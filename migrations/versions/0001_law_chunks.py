"""law_chunks table (docs/milestones/M3.md 6.3)

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_TABLE = """
CREATE TABLE law_chunks (
    id               text PRIMARY KEY,
    source           text NOT NULL,
    source_url       text NOT NULL,
    doc_type         text NOT NULL CHECK (doc_type IN ('statute','regulation','decision','case_law','guidance')),
    authority_tier   text NOT NULL CHECK (authority_tier IN ('statute','regulation','decision','case_law','guidance')),
    jurisdiction     text NOT NULL,
    extent           text,
    heading_path     text[] NOT NULL,
    in_force_from    date NOT NULL,
    in_force_to      date,
    text_original    text NOT NULL,
    text_contextual  text,
    embedding        vector(1024),
    embedding_model  text,
    topics           text[] NOT NULL DEFAULT '{}',
    holdout          boolean NOT NULL DEFAULT false,
    licence          text NOT NULL,
    attribution      text NOT NULL,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    source_sha256    text NOT NULL,
    chunk_sha256     text NOT NULL,
    search_tsv       tsvector GENERATED ALWAYS AS
                     (to_tsvector('english', coalesce(text_contextual, text_original))) STORED,
    CHECK (in_force_to IS NULL OR in_force_to > in_force_from),
    CHECK ((embedding IS NULL) = (embedding_model IS NULL))
)
"""  # noqa: E501

STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    CREATE_TABLE,
    "CREATE INDEX law_chunks_embedding_idx ON law_chunks "
    "USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX law_chunks_search_idx ON law_chunks USING gin (search_tsv)",
    "CREATE INDEX law_chunks_validity_idx ON law_chunks (in_force_from, in_force_to)",
    "CREATE INDEX law_chunks_source_idx ON law_chunks (source)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # The extension stays: other things may use it.
    op.execute("DROP TABLE law_chunks")
