# Worker

Python worker that claims `QUEUED` tasks from PostgreSQL. It currently **claims only**: a claimed task becomes `RUNNING` with `worker_id` and `started_at` set, and stays there (execution comes next).

## Run

```bash
uv sync
DATABASE_URL=postgresql://postgres@localhost:5432/<db> uv run python -m agent_worker --once [--worker-id ID]
```

Prints one JSON line: `{"claimed": true, "task_id": "...", "worker_id": "..."}` or `{"claimed": false, "worker_id": "..."}`. `DATABASE_URL` has no default on purpose, so it never claims from a database by accident. The password comes from `PGPASSWORD`.

If `uv run python -m agent_worker` says *No module named agent_worker*: on macOS uv marks `.venv` hidden and Python 3.12+ skips hidden `.pth` files. Prefix the command with `PYTHONPATH=src`.

## How claiming is safe

One `UPDATE … WHERE id = (SELECT … ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING …`, committed immediately ([claim.py](src/agent_worker/claim.py)):
- `FOR UPDATE` locks the chosen row, so two workers can't claim the same task.
- `SKIP LOCKED` makes other workers take the next task instead of waiting.
- Oldest first; only `QUEUED` tasks; on any error nothing changes.

## Test

```bash
uv run pytest            # claim tests: real Postgres, database agent_worker_test (created automatically)
uv run pytest -m e2e     # POST /tasks on the real Java API → worker process claims → GET /tasks/{id}
```

- **Claim tests** rebuild `agent_worker_test` from the API's Flyway migrations each session. They cover FIFO order, ignoring non-`QUEUED` tasks, claim-once, commit visibility (autocommit or not), rollback on failure, skipping locked rows without waiting, and 8 concurrent workers × 200 tasks claimed exactly once.
- **E2E tests** start the API jar (built if missing; rebuild with `../api-service/mvnw -DskipTests package` after API changes) on a free port against a dedicated `agent_executor_e2e` database, emptied before each test, and run the worker as a real process. The API needs `GITHUB_TOKEN` to validate repositories.

Override databases with `WORKER_TEST_DATABASE_URL` / `WORKER_E2E_DATABASE_URL`.
