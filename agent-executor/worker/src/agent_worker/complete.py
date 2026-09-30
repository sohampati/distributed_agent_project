from __future__ import annotations

import uuid

import psycopg

# Guarded on status and owner: only the worker that claimed a task can finish it, and only once.
# (Groundwork for leases: a worker whose task was reassigned can't overwrite the new owner's outcome.)
_FINISH_SQL = """
    UPDATE tasks
    SET status = %(status)s,
        result = %(result)s,
        error = %(error)s,
        completed_at = (now() AT TIME ZONE 'utc')
    WHERE id = %(id)s
      AND status = 'RUNNING'
      AND worker_id = %(worker_id)s
"""


def complete_task(conn: psycopg.Connection, task_id: uuid.UUID, worker_id: str, result: str) -> bool:
    """Marks the task SUCCEEDED with ``result``. Returns False if this worker doesn't own a RUNNING task by that id."""
    return _finish(conn, task_id, worker_id, status="SUCCEEDED", result=result, error=None)


def fail_task(conn: psycopg.Connection, task_id: uuid.UUID, worker_id: str, error: str) -> bool:
    """Marks the task FAILED with ``error``. Returns False if this worker doesn't own a RUNNING task by that id."""
    return _finish(conn, task_id, worker_id, status="FAILED", result=None, error=error)


def _finish(conn: psycopg.Connection, task_id: uuid.UUID, worker_id: str, **values) -> bool:
    with conn.transaction():
        cur = conn.execute(_FINISH_SQL, {"id": task_id, "worker_id": worker_id, **values})
        return cur.rowcount == 1
