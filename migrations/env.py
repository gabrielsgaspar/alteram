"""Alembic environment. The URL comes from ALTERAM_DATABASE_URL via alteram.db."""

from alembic import context
from sqlalchemy import create_engine, pool

from alteram.db import database_url


def sqlalchemy_url() -> str:
    """The app URL with the psycopg 3 driver named, as SQLAlchemy needs."""
    url = database_url()
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=sqlalchemy_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(sqlalchemy_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
