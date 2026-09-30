"""Finishing a task: only the worker that claimed it, only while it is RUNNING, exactly once."""

from __future__ import annotations

from datetime import timedelta

import pytest

from agent_worker.claim import claim_next_task
from agent_worker.complete import complete_task, fail_task
from tests.helpers import insert_task, task_row, utc_now


@pytest.fixture
def running_task(conn):
    insert_task(conn)
    return claim_next_task(conn, "worker-1")


def test_complete_marks_task_succeeded_with_result(conn, running_task):
    before = utc_now()

    assert complete_task(conn, running_task.id, "worker-1", "diff --git a/x b/x") is True

    row = task_row(conn, running_task.id)
    assert row["status"] == "SUCCEEDED"
    assert row["result"] == "diff --git a/x b/x"
    assert row["error"] is None
    assert row["worker_id"] == "worker-1"
    assert before - timedelta(seconds=1) <= row["completed_at"] <= utc_now() + timedelta(seconds=1)
    assert row["completed_at"] >= row["started_at"]


def test_fail_marks_task_failed_with_error(conn, running_task):
    assert fail_task(conn, running_task.id, "worker-1", "sandbox exited with code 1") is True

    row = task_row(conn, running_task.id)
    assert row["status"] == "FAILED"
    assert row["error"] == "sandbox exited with code 1"
    assert row["result"] is None
    assert row["completed_at"] is not None


@pytest.mark.parametrize("finish", [complete_task, fail_task])
def test_another_worker_cannot_finish_the_task(conn, running_task, finish):
    assert finish(conn, running_task.id, "worker-2", "x") is False

    row = task_row(conn, running_task.id)
    assert (row["status"], row["worker_id"], row["completed_at"]) == ("RUNNING", "worker-1", None)


@pytest.mark.parametrize("finish", [complete_task, fail_task])
def test_queued_task_cannot_be_finished(conn, finish):
    task_id = insert_task(conn)

    assert finish(conn, task_id, "worker-1", "x") is False
    assert task_row(conn, task_id)["status"] == "QUEUED"


def test_a_task_is_finished_only_once(conn, running_task):
    assert complete_task(conn, running_task.id, "worker-1", "first") is True

    assert complete_task(conn, running_task.id, "worker-1", "second") is False
    assert fail_task(conn, running_task.id, "worker-1", "late failure") is False

    row = task_row(conn, running_task.id)
    assert (row["status"], row["result"], row["error"]) == ("SUCCEEDED", "first", None)


def test_large_result_is_stored_verbatim(conn, running_task):
    big_diff = "+line\n" * 100_000  # 600 KB

    complete_task(conn, running_task.id, "worker-1", big_diff)

    assert task_row(conn, running_task.id)["result"] == big_diff
