"""POST /tasks on the real API → the worker process claims it → GET /tasks/{id} shows it RUNNING."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tests.helpers import PUBLIC_REPO, task_row

pytestmark = pytest.mark.e2e


def test_posted_task_is_claimed_by_the_worker(api, db, run_worker):
    created = api.post_task(PUBLIC_REPO, "Add a health endpoint and write tests")
    assert created.status == 202, created
    task_id = created.body["task_id"]
    assert api.get_task(task_id).body["status"] == "QUEUED"

    run = run_worker("e2e-worker-1")

    assert run.returncode == 0, run.stderr
    assert run.output == {"claimed": True, "task_id": task_id, "worker_id": "e2e-worker-1"}

    task = api.get_task(task_id)
    assert task.status == 200, task
    assert task.body["status"] == "RUNNING"
    assert task.body["worker_id"] == "e2e-worker-1"
    started_at = datetime.fromisoformat(task.body["started_at"])
    created_at = datetime.fromisoformat(task.body["created_at"])
    assert started_at >= created_at
    assert task.body["completed_at"] is None  # the API returns null fields explicitly

    row = task_row(db, uuid.UUID(task_id))
    assert (row["status"], row["worker_id"]) == ("RUNNING", "e2e-worker-1")


def test_worker_with_empty_queue_claims_nothing(api, db, run_worker):
    run = run_worker("e2e-worker-1")

    assert run.returncode == 0, run.stderr
    assert run.output == {"claimed": False, "worker_id": "e2e-worker-1"}


def test_worker_claims_tasks_in_the_order_they_were_posted(api, db, run_worker):
    first = api.post_task(PUBLIC_REPO, "first").body["task_id"]
    second = api.post_task(PUBLIC_REPO, "second").body["task_id"]

    assert run_worker("e2e-worker-1").output["task_id"] == first
    assert api.get_task(second).body["status"] == "QUEUED"

    assert run_worker("e2e-worker-1").output["task_id"] == second
    assert run_worker("e2e-worker-1").output["claimed"] is False


def test_rejected_post_never_reaches_the_worker(api, db, run_worker):
    rejected = api.post_task("https://gitlab.com/example/project", "not a GitHub repo")
    assert rejected.status == 400, rejected

    assert run_worker("e2e-worker-1").output["claimed"] is False
