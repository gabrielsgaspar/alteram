import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from alteram import db
from alteram.models import Argument, Case, CounterPoint, Point

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parents[1]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "db: needs a Postgres test database (ALTERAM_TEST_DATABASE_URL)"
    )


def require_test_database() -> str:
    """The test database URL; skip when unset, or fail if ALTERAM_REQUIRE_DB=1."""
    url = db.test_database_url()
    if url is None:
        if os.environ.get("ALTERAM_REQUIRE_DB") == "1":
            pytest.fail("ALTERAM_REQUIRE_DB=1 but ALTERAM_TEST_DATABASE_URL is not set")
        pytest.skip("no test database")
    return url


@pytest.fixture(scope="session")
def migrated_test_database() -> Iterator[str]:
    url = require_test_database()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    previous = os.environ.get("ALTERAM_DATABASE_URL")
    os.environ["ALTERAM_DATABASE_URL"] = url
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            del os.environ["ALTERAM_DATABASE_URL"]
        else:
            os.environ["ALTERAM_DATABASE_URL"] = previous
    yield url


@pytest.fixture
def pg_conn(migrated_test_database: str) -> Iterator[psycopg.Connection]:
    conn = db.connect(migrated_test_database)
    try:
        conn.execute("TRUNCATE law_chunks")
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def no_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may send LangSmith traces, whatever the shell has set."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


@pytest.fixture
def case() -> Case:
    return Case(
        id="case-x",
        title="Small case",
        kind="balanced",
        expected="claimant",
        paragraphs={1: "One.", 2: "Two.", 3: "Three."},
        sha256="0" * 64,
    )


def make_argument(side: str, citations: list[list[int]]) -> Argument:
    """An argument whose points carry a wrong model-supplied label."""
    return Argument(
        side=side,
        points=[
            Point(label="X9", claim="c", reasoning="r", citations=c) for c in citations
        ],
        strongest_point_against=CounterPoint(point="p", answer="a", citations=[1]),
        requested_outcome="win",
    )
