from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import class_row


@dataclass(frozen=True)
class ClaimedTask:
    id: uuid.UUID
    repository_url: str
    prompt: str
    status: str
    worker_id: str
    created_at: datetime
    started_at: datetime


# One statement, so the pick and the update are atomic:
# - FOR UPDATE locks the chosen row until commit, so no other worker can claim it too.
# - SKIP LOCKED makes other workers pass over rows being claimed instead of queueing behind them.
# - The status check is repeated in the outer WHERE as a guard in case the row changed.
# Timestamps are naive UTC, matching how the API writes created_at.
_CLAIM_SQL = """
    UPDATE tasks
    SET status = 'RUNNING',
        worker_id = %(worker_id)s,
        started_at = (now() AT TIME ZONE 'utc')
    WHERE id = (
        SELECT id FROM tasks
        WHERE status = 'QUEUED'
        ORDER BY created_at, id
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
      AND status = 'QUEUED'
    RETURNING id, repository_url, prompt, status, worker_id, created_at, started_at
"""


def claim_next_task(conn: psycopg.Connection, worker_id: str) -> ClaimedTask | None:
    """Claims the oldest QUEUED task for ``worker_id`` and commits, or returns None if there is none.

    ``conn`` should be in autocommit mode so the claim commits here; on error nothing is changed.
    """
    with conn.transaction(), conn.cursor(row_factory=class_row(ClaimedTask)) as cur:
        return cur.execute(_CLAIM_SQL, {"worker_id": worker_id}).fetchone()
