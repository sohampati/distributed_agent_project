"""Shared database helpers for worker tests.

Tests run against real PostgreSQL: claim safety depends on row locks and SKIP LOCKED, which a mock can't prove.
Connection settings come from the usual libpq variables (PGPASSWORD etc.).
"""

from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

# The Java service owns the schema (Flyway); tests build theirs from the same migration files.
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "api-service" / "src" / "main" / "resources" / "db" / "migration"

PUBLIC_REPO = "https://github.com/spring-projects/spring-boot"

WORKER_DIR = Path(__file__).resolve().parents[1]
STUB_IMAGE_DIR = WORKER_DIR / "sandbox" / "stub"
STUB_TEST_IMAGE = "agent-sandbox-stub:test"
DISK_HELPER_IMAGE_DIR = WORKER_DIR / "sandbox" / "disk-helper"
DISK_HELPER_TEST_IMAGE = "agent-sandbox-disk-helper:test"


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def build_image(tag: str, context: Path) -> str:
    """Builds an image (cached layers make repeat builds fast)."""
    subprocess.run(["docker", "build", "-q", "-t", tag, str(context)], check=True, capture_output=True)
    return tag


def build_stub_image(tag: str = STUB_TEST_IMAGE) -> str:
    return build_image(tag, STUB_IMAGE_DIR)


def build_disk_helper_image(tag: str = DISK_HELPER_TEST_IMAGE) -> str:
    return build_image(tag, DISK_HELPER_IMAGE_DIR)


def ensure_database(url: str) -> None:
    """Creates the database named in ``url`` if it doesn't exist."""
    dbname = conninfo_to_dict(url)["dbname"]
    admin_url = make_conninfo(url, dbname="postgres")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            admin.execute(f'CREATE DATABASE "{dbname}"')


def migration_files() -> list[Path]:
    """Flyway migrations (V1__x.sql, V2__y.sql, ...) in version order."""
    files = list(MIGRATIONS_DIR.glob("V*__*.sql"))
    assert files, f"no migrations found in {MIGRATIONS_DIR}"
    return sorted(files, key=lambda f: int(f.name[1:].split("__")[0]))


def utc_now() -> datetime:
    """Naive UTC wall-clock time, matching how timestamps are stored (timestamp without time zone)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def insert_task(
    conn: psycopg.Connection,
    *,
    status: str = "QUEUED",
    created_at: datetime | None = None,
    prompt: str = "test task",
    worker_id: str | None = None,
) -> uuid.UUID:
    task_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO tasks (id, repository_url, prompt, status, worker_id, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (task_id, PUBLIC_REPO, prompt, status, worker_id, created_at or utc_now()),
    )
    return task_id


def task_row(conn: psycopg.Connection, task_id: uuid.UUID) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
    assert row is not None, f"task {task_id} not found"
    return row
