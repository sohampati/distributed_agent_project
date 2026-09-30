"""Safe claiming: every QUEUED task is claimed by exactly one worker, oldest first, atomically."""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter
from datetime import timedelta

import psycopg
import pytest

from agent_worker.claim import ClaimedTask, claim_next_task
from tests.helpers import PUBLIC_REPO, insert_task, task_row, utc_now


# ---- basic contract ---------------------------------------------------------------------------------------------


def test_empty_queue_returns_none(conn):
    assert claim_next_task(conn, "worker-1") is None


def test_claim_marks_task_running_and_returns_it(conn):
    task_id = insert_task(conn, prompt="Add a health endpoint")
    before = utc_now()

    claimed = claim_next_task(conn, "worker-1")

    after = utc_now()
    assert isinstance(claimed, ClaimedTask)
    assert claimed.id == task_id
    assert claimed.repository_url == PUBLIC_REPO
    assert claimed.prompt == "Add a health endpoint"
    assert claimed.status == "RUNNING"
    assert claimed.worker_id == "worker-1"
    # started_at is naive UTC like created_at; allow slack for the DB and test clocks.
    assert before - timedelta(seconds=1) <= claimed.started_at <= after + timedelta(seconds=1)

    row = task_row(conn, task_id)
    assert row["status"] == "RUNNING"
    assert row["worker_id"] == "worker-1"
    assert row["started_at"] == claimed.started_at
    assert row["completed_at"] is None
    assert row["result"] is None
    assert row["error"] is None


def test_claims_oldest_task_first(conn):
    now = utc_now()
    newest = insert_task(conn, created_at=now)
    oldest = insert_task(conn, created_at=now - timedelta(minutes=10))
    middle = insert_task(conn, created_at=now - timedelta(minutes=5))

    claimed = [claim_next_task(conn, "worker-1").id for _ in range(3)]

    assert claimed == [oldest, middle, newest]


@pytest.mark.parametrize("status", ["RUNNING", "SUCCEEDED", "FAILED"])
def test_ignores_tasks_that_are_not_queued(conn, status):
    task_id = insert_task(conn, status=status, worker_id="someone-else" if status == "RUNNING" else None)

    assert claim_next_task(conn, "worker-1") is None
    assert task_row(conn, task_id)["status"] == status


def test_a_task_is_claimed_only_once(conn):
    task_id = insert_task(conn)

    first = claim_next_task(conn, "worker-1")
    second = claim_next_task(conn, "worker-2")

    assert first.id == task_id
    assert second is None
    assert task_row(conn, task_id)["worker_id"] == "worker-1"


# ---- transactional safety ---------------------------------------------------------------------------------------


def test_claim_is_committed_and_visible_to_other_connections(conn, connect):
    task_id = insert_task(conn)
    worker_conn = connect()

    claim_next_task(worker_conn, "worker-1")

    # A different session sees the claim immediately: nothing is left in an open transaction.
    assert task_row(connect(), task_id)["status"] == "RUNNING"
    assert worker_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


def test_claim_commits_even_on_a_non_autocommit_connection(conn, connect):
    task_id = insert_task(conn)
    worker_conn = connect(autocommit=False)

    claim_next_task(worker_conn, "worker-1")

    # Otherwise the claim would sit in an open transaction, holding the row lock and invisible to everyone else.
    assert worker_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    assert task_row(connect(), task_id)["status"] == "RUNNING"


def test_failed_claim_leaves_task_queued(conn):
    task_id = insert_task(conn)
    too_long_worker_id = "w" * 101  # tasks.worker_id is varchar(100)

    with pytest.raises(Exception):
        claim_next_task(conn, too_long_worker_id)

    row = task_row(conn, task_id)
    assert row["status"] == "QUEUED"
    assert row["worker_id"] is None
    assert row["started_at"] is None
    # The connection is still usable, and the task is still claimable.
    assert claim_next_task(conn, "worker-1").id == task_id


def test_skips_a_task_locked_by_another_worker_instead_of_waiting(conn, connect):
    now = utc_now()
    locked = insert_task(conn, created_at=now - timedelta(minutes=1))
    free = insert_task(conn, created_at=now)

    # Another worker is mid-claim on the oldest task: it holds the row lock in an open transaction.
    other_worker = connect(autocommit=False)
    other_worker.execute("SELECT id FROM tasks WHERE id = %s FOR UPDATE", (locked,))

    worker_conn = connect()
    # If the claim waited on the lock instead of skipping it, this turns the hang into a fast failure.
    worker_conn.execute("SET lock_timeout = '2s'")
    start = time.monotonic()
    claimed = claim_next_task(worker_conn, "worker-1")
    elapsed = time.monotonic() - start

    assert claimed.id == free
    assert elapsed < 1.0, f"claim blocked for {elapsed:.2f}s instead of skipping the locked row"
    assert task_row(conn, locked)["status"] == "QUEUED"

    # Once the lock is released, the skipped task is claimable again.
    other_worker.rollback()
    assert claim_next_task(worker_conn, "worker-1").id == locked


def test_concurrent_workers_claim_every_task_exactly_once(conn, connect):
    task_count, worker_count = 200, 8
    task_ids = {insert_task(conn) for _ in range(task_count)}

    claims: dict[str, list[uuid.UUID]] = {f"worker-{n}": [] for n in range(worker_count)}
    errors: list[BaseException] = []
    start_line = threading.Barrier(worker_count)  # maximise contention: everyone starts at once

    def run_worker(worker_id: str) -> None:
        try:
            worker_conn = connect()
            start_line.wait()
            # Capped so a claim that never returns None (e.g. re-claiming RUNNING tasks) fails fast instead of spinning.
            while len(claims[worker_id]) <= task_count and (task := claim_next_task(worker_conn, worker_id)):
                claims[worker_id].append(task.id)
        except BaseException as e:  # surfaced below; a thread's exception is otherwise lost
            errors.append(e)

    threads = [threading.Thread(target=run_worker, args=(worker_id,), daemon=True) for worker_id in claims]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not any(thread.is_alive() for thread in threads), "workers still running after 30s"
    assert not errors, errors
    all_claims = [task_id for ids in claims.values() for task_id in ids]
    duplicates = [task_id for task_id, n in Counter(all_claims).items() if n > 1]
    assert not duplicates, f"claimed more than once: {duplicates}"
    assert set(all_claims) == task_ids, "some tasks were never claimed"

    # The database agrees with what each worker thinks it claimed.
    for worker_id, ids in claims.items():
        for task_id in ids:
            row = task_row(conn, task_id)
            assert (row["status"], row["worker_id"]) == ("RUNNING", worker_id)
    # And more than one worker actually got work (otherwise this didn't test concurrency).
    assert sum(1 for ids in claims.values() if ids) > 1
