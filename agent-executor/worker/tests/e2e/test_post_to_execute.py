"""POST /tasks on the real API → the worker claims it and runs it in a Docker sandbox → GET /tasks/{id} shows the outcome."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from tests.helpers import task_row

pytestmark = pytest.mark.e2e

# Tiny public repository: cloning it takes well under a second.
HELLO_WORLD = "https://github.com/octocat/Hello-World"


def test_posted_task_is_executed_and_its_diff_recorded(api, db, run_worker):
    created = api.post_task(HELLO_WORLD, "Add a health endpoint and write tests")
    assert created.status == 202, created
    task_id = created.body["task_id"]
    assert api.get_task(task_id).body["status"] == "QUEUED"

    run = run_worker("e2e-worker-1")

    assert run.returncode == 0, run.stderr
    assert run.output == {"claimed": True, "task_id": task_id, "worker_id": "e2e-worker-1", "status": "SUCCEEDED"}

    task = api.get_task(task_id)
    assert task.status == 200, task
    assert task.body["status"] == "SUCCEEDED"
    assert task.body["worker_id"] == "e2e-worker-1"
    assert task.body["error"] is None
    # The stub agent wrote AGENT_NOTES.md containing the prompt; the result is the git diff of that change.
    assert "diff --git a/AGENT_NOTES.md b/AGENT_NOTES.md" in task.body["result"]
    assert "+Task: Add a health endpoint and write tests" in task.body["result"]

    created_at, started_at, completed_at = (
        datetime.fromisoformat(task.body[k]) for k in ("created_at", "started_at", "completed_at"))
    assert created_at <= started_at <= completed_at

    row = task_row(db, uuid.UUID(task_id))
    assert (row["status"], row["worker_id"]) == ("SUCCEEDED", "e2e-worker-1")


def test_failing_agent_marks_the_task_failed(api, db, run_worker):
    task_id = api.post_task(HELLO_WORLD, "Break things [stub:fail]").body["task_id"]

    run = run_worker("e2e-worker-1")

    assert run.returncode == 0, run.stderr  # a failed task is a normal outcome, not a worker crash
    assert run.output["status"] == "FAILED"
    task = api.get_task(task_id).body
    assert task["status"] == "FAILED"
    assert "exited with code 1" in task["error"]
    assert "failing as requested" in task["error"]
    assert task["result"] is None
    assert task["completed_at"] is not None


def test_worker_with_empty_queue_claims_nothing(api, db, run_worker):
    run = run_worker("e2e-worker-1")

    assert run.returncode == 0, run.stderr
    assert run.output == {"claimed": False, "worker_id": "e2e-worker-1"}


def test_worker_takes_tasks_in_the_order_they_were_posted(api, db, run_worker):
    first = api.post_task(HELLO_WORLD, "first").body["task_id"]
    second = api.post_task(HELLO_WORLD, "second").body["task_id"]

    assert run_worker("e2e-worker-1").output["task_id"] == first
    assert api.get_task(first).body["status"] == "SUCCEEDED"
    assert api.get_task(second).body["status"] == "QUEUED"

    assert run_worker("e2e-worker-1").output["task_id"] == second
    assert run_worker("e2e-worker-1").output["claimed"] is False


def test_rejected_post_never_reaches_the_worker(api, db, run_worker):
    rejected = api.post_task("https://gitlab.com/example/project", "not a GitHub repo")
    assert rejected.status == 400, rejected

    assert run_worker("e2e-worker-1").output["claimed"] is False
