"""Database configuration. URLs come from environment variables only."""

import os
from urllib.parse import urlparse

import psycopg


def database_url() -> str:
    """The app database URL from ALTERAM_DATABASE_URL."""
    url = os.environ.get("ALTERAM_DATABASE_URL")
    if not url:
        raise RuntimeError("ALTERAM_DATABASE_URL is not set")
    return url


def test_database_url() -> str | None:
    """The test database URL, or None if unset. The database name must end `_test`."""
    url = os.environ.get("ALTERAM_TEST_DATABASE_URL")
    if not url:
        return None
    name = urlparse(url).path.lstrip("/")
    if not name.endswith("_test"):
        raise RuntimeError(
            "ALTERAM_TEST_DATABASE_URL must name a database ending in '_test', "
            f"got {name!r}"
        )
    return url


def connect(url: str) -> psycopg.Connection:
    """Open an autocommit psycopg 3 connection. `postgresql+psycopg://` is accepted."""
    plain = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(plain, autocommit=True)
