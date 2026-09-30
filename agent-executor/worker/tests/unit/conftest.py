from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import psycopg
import pytest

from tests.helpers import ensure_database, migration_files

# A database of its own, so these tests never race the Java tests (agent_executor_test) or real data.
TEST_DATABASE_URL = os.environ.get("WORKER_TEST_DATABASE_URL", "postgresql://postgres@localhost:5432/agent_worker_test")


@pytest.fixture(scope="session")
def database_url() -> str:
    """Rebuilds the schema from the Flyway migrations once per test session."""
    ensure_database(TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS tasks")
        for migration in migration_files():
            conn.execute(migration.read_text())
    return TEST_DATABASE_URL


@pytest.fixture
def connect(database_url: str) -> Iterator[Callable[..., psycopg.Connection]]:
    """Factory for extra connections (one per simulated worker); all are closed after the test."""
    opened: list[psycopg.Connection] = []

    def _connect(*, autocommit: bool = True) -> psycopg.Connection:
        conn = psycopg.connect(database_url, autocommit=autocommit)
        opened.append(conn)
        return conn

    yield _connect
    for conn in opened:
        conn.close()


@pytest.fixture
def conn(connect: Callable[..., psycopg.Connection]) -> psycopg.Connection:
    """An autocommit connection on an empty tasks table."""
    conn = connect()
    conn.execute("DELETE FROM tasks")
    return conn
