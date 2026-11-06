"""Run the migration offline (no connection) and check the SQL it emits."""

import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def offline_sql(monkeypatch: pytest.MonkeyPatch, direction: str) -> str:
    monkeypatch.setenv(
        "ALTERAM_DATABASE_URL", "postgresql+psycopg://u@localhost/x_test"
    )
    buffer = io.StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=buffer)
    config.set_main_option("script_location", str(ROOT / "migrations"))
    if direction == "up":
        command.upgrade(config, "head", sql=True)
    else:
        command.downgrade(config, "0001:base", sql=True)
    return " ".join(buffer.getvalue().split())


def test_upgrade_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    sql = offline_sql(monkeypatch, "up")
    for expected in [
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE TABLE law_chunks",
        "USING hnsw (embedding vector_cosine_ops)",
        "USING gin (search_tsv)",
        "CHECK (in_force_to IS NULL OR in_force_to > in_force_from)",
        "CHECK ((embedding IS NULL) = (embedding_model IS NULL))",
        "embedding vector(1024)",
    ]:
        assert expected in sql


def test_downgrade_drops_table_but_not_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sql = offline_sql(monkeypatch, "down")
    assert "DROP TABLE law_chunks" in sql
    assert "DROP EXTENSION" not in sql


def test_alembic_ini_has_no_url() -> None:
    text = (ROOT / "alembic.ini").read_text()
    assert "script_location = migrations" in text
    assert "sqlalchemy.url" not in text
