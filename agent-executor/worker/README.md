# Worker

Python worker that claims `QUEUED` tasks from PostgreSQL and runs each one in an isolated Docker container:

```
claim (QUEUED → RUNNING) → shallow clone → run agent in sandbox → git diff → SUCCEEDED (diff in result) / FAILED (error)
```

The agent is currently a **stub** ([sandbox/stub](sandbox/stub)) that writes the prompt into `AGENT_NOTES.md`, so the pipeline can be tested without an LLM. A real agent replaces the image; nothing else changes.

## Prerequisites

- Docker. On macOS without Docker Desktop: [Colima](https://github.com/abiosoft/colima) (`colima start --cpu 2 --memory 4 --vm-type vz`).
- The images: `docker build -t agent-sandbox-stub sandbox/stub` and `docker build -t agent-sandbox-disk-helper sandbox/disk-helper`

## Run

```bash
uv sync
DATABASE_URL=postgresql://postgres@localhost:5432/<db> uv run python -m agent_worker --once [--worker-id ID]
```

Prints one JSON line: `{"claimed": true, "task_id": "...", "worker_id": "...", "status": "SUCCEEDED"}` or `{"claimed": false, "worker_id": "..."}`.

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | *(required)* | No default on purpose, so it never runs tasks from a database by accident. Password from `PGPASSWORD`. |
| `GITHUB_TOKEN` | *(none)* | Used by the worker to clone; never passed into the sandbox. |
| `SANDBOX_IMAGE` | `agent-sandbox-stub:latest` | Agent image. |
| `SANDBOX_TIMEOUT_SECONDS` | `600` | Container is killed and the task FAILED after this. |
| `SANDBOX_DISK_SIZE` | `2g` | Size of the agent's `/workspace` filesystem (e.g. `512m`, `2g`). |
| `SANDBOX_DISK_HELPER_IMAGE` | `agent-sandbox-disk-helper:latest` | Creates/destroys task disks. |
| `WORKSPACE_ROOT` | `~/.cache/agent-worker/workspaces` | Where the worker clones; any directory works (the sandbox gets a copy). |

If `uv run python -m agent_worker` says *No module named agent_worker*: on macOS uv marks `.venv` hidden and Python 3.12+ skips hidden `.pth` files. Prefix the command with `PYTHONPATH=src`.

## Safety

**Claiming** ([claim.py](src/agent_worker/claim.py)): one `UPDATE … WHERE id = (SELECT … ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED)`, committed immediately. Two workers can't claim the same task; others skip rows being claimed instead of waiting.

**Finishing** ([complete.py](src/agent_worker/complete.py)): only while `RUNNING` and only by the worker in `worker_id`, exactly once. Any unexpected error still marks the task FAILED rather than leaving it RUNNING.

**Sandbox** ([sandbox.py](src/agent_worker/sandbox.py)), one fresh container per task:
- no network (`--network=none`), all capabilities dropped, `no-new-privileges`, never `--privileged`, no Docker socket
- runs as the worker's (non-root) uid; refuses to run if the worker is root
- read-only root filesystem; only `/workspace` and a 256 MB `/tmp` tmpfs are writable
- `/workspace` is the task's **own fixed-size disk** (`SANDBOX_DISK_SIZE`): writes past it fail with "No space left on device". **No host directory is mounted**: the repo is copied in before the run and the disk's contents copied back after (not after a timeout)
- memory (no swap), CPU and process-count limits; wall-clock timeout
- environment contains only `TASK_PROMPT` and `HOME` — no token, no DB password
- container and disk always removed; both carry the label `agent-worker.sandbox` (`docker ps -a` / `docker volume ls --filter label=agent-worker.sandbox`)

**Task disks** ([disk.py](src/agent_worker/disk.py)): Docker can't cap volume sizes on Colima's filesystem, so each task gets a sparse ext4 image (in `/var/lib/agent-worker/disks` inside the VM, never on the Mac) attached to a loop device and mounted `nosuid,nodev`. Attaching loop devices needs a **privileged helper container**; it runs offline, sees only the disk directory, and only executes fixed commands built from validated values (size, generated names) — never task input. Overhead is about 0.4 s per task.

**Git** ([repo.py](src/agent_worker/repo.py)): the token is passed to `git clone` via environment config, never argv. The repository's `.git` lives *outside* the mounted directory, so the sandbox can't plant hooks or config (e.g. `core.fsmonitor`) that the worker's own `git diff` would execute on the host.

## Test

```bash
uv run pytest            # unit + Docker tests (Docker tests skip if Docker isn't running)
uv run pytest -m e2e     # POST /tasks on the real Java API → worker process → GET /tasks/{id}
```

| Suite | Needs | Covers |
|---|---|---|
| `tests/unit/test_claim.py` | Postgres | FIFO, claim-once, commit visibility, rollback, SKIP LOCKED, 8 workers × 200 tasks |
| `tests/unit/test_complete.py` | Postgres | owner-only, RUNNING-only, exactly-once finishing |
| `tests/unit/test_sandbox_args.py` | — | every isolation flag present; no secrets, sockets, privileged mode or host mounts |
| `tests/unit/test_disk.py` | — | privileged helper only gets validated sizes/paths (no shell injection), runs offline; volume `nosuid,nodev` |
| `tests/unit/test_repo.py` | git | clone, `.git` outside work tree, diff of new/modified/deleted files, token not in argv |
| `tests/unit/test_executor.py` | Postgres | success, agent failure, timeout, clone failure, crash; workspace always removed; output truncation |
| `tests/docker/` | Docker | real containers: stub agent, exit codes, timeout kill, memory, process & **disk** limits, no network, non-root, read-only rootfs, no host mounts, no secrets, no `.git`, changes copied back (incl. deletions, ownership); no leftover containers, volumes, disk images or loop devices |
| `tests/e2e/` | Docker, Java API, GitHub | POST → execute → GET `SUCCEEDED` with diff; agent failure → `FAILED`; FIFO; empty queue; rejected POST |

Unit tests use `agent_worker_test` (rebuilt from the API's Flyway migrations); E2E uses `agent_executor_e2e`, starting the API jar (built if missing; rebuild with `../api-service/mvnw -DskipTests package` after API changes). Both databases are created automatically. Override with `WORKER_TEST_DATABASE_URL` / `WORKER_E2E_DATABASE_URL`.
