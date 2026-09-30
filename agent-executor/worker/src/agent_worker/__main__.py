"""Worker entry point: ``python -m agent_worker --once [--worker-id ID]``.

Claims one QUEUED task, runs it in a Docker sandbox and records SUCCEEDED/FAILED.
Prints one JSON line on stdout describing what happened; logs go to stderr.
Only ``--once`` exists so far: the polling loop comes next, test first.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
from pathlib import Path

import psycopg

from agent_worker.claim import claim_next_task
from agent_worker.executor import execute_task
from agent_worker.sandbox import DockerSandbox, SandboxConfig

log = logging.getLogger("agent_worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_worker", description="Claim QUEUED tasks from PostgreSQL.")
    parser.add_argument("--once", action="store_true", required=True, help="claim at most one task, then exit")
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-{os.getpid()}",
                        help="stored in tasks.worker_id (default: hostname-pid)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Deliberately no default, so the worker never claims (and runs) tasks from a database by accident.
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is not set (e.g. postgresql://postgres@localhost:5432/agent_executor_e2e)")

    sandbox = DockerSandbox(SandboxConfig(
        image=os.environ.get("SANDBOX_IMAGE", "agent-sandbox-stub:latest"),
        timeout_seconds=float(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "600")),
        disk_size=os.environ.get("SANDBOX_DISK_SIZE", "2g"),
        disk_helper_image=os.environ.get("SANDBOX_DISK_HELPER_IMAGE", "agent-sandbox-disk-helper:latest"),
    ))
    # Where the worker clones repositories; the sandbox gets a copy on its own disk, never this directory.
    workspace_root = Path(os.environ.get("WORKSPACE_ROOT", Path.home() / ".cache" / "agent-worker" / "workspaces"))

    with psycopg.connect(database_url, autocommit=True) as conn:
        task = claim_next_task(conn, args.worker_id)
        if task is None:
            log.info("%s: no QUEUED tasks", args.worker_id)
            print(json.dumps({"claimed": False, "worker_id": args.worker_id}))
            return 0

        log.info("%s: claimed task %s (%s)", args.worker_id, task.id, task.repository_url)
        outcome = execute_task(task, conn=conn, worker_id=args.worker_id, sandbox=sandbox,
                               workspace_root=workspace_root, token=os.environ.get("GITHUB_TOKEN") or None)
        log.info("%s: task %s %s", args.worker_id, task.id, outcome.status)

    print(json.dumps({"claimed": True, "task_id": str(task.id), "worker_id": args.worker_id,
                      "status": outcome.status}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
