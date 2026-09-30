"""Worker entry point: ``python -m agent_worker --once [--worker-id ID]``.

Prints one JSON line on stdout describing what happened; logs go to stderr.
Only ``--once`` exists so far: the polling loop and task execution come next, test first.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys

import psycopg

from agent_worker.claim import claim_next_task

log = logging.getLogger("agent_worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_worker", description="Claim QUEUED tasks from PostgreSQL.")
    parser.add_argument("--once", action="store_true", required=True, help="claim at most one task, then exit")
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-{os.getpid()}",
                        help="stored in tasks.worker_id (default: hostname-pid)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Deliberately no default: claimed tasks stay RUNNING until execution exists, so never claim from a DB by accident.
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is not set (e.g. postgresql://postgres@localhost:5432/agent_executor_e2e)")

    with psycopg.connect(database_url, autocommit=True) as conn:
        task = claim_next_task(conn, args.worker_id)

    if task is None:
        log.info("%s: no QUEUED tasks", args.worker_id)
        print(json.dumps({"claimed": False, "worker_id": args.worker_id}))
    else:
        log.info("%s: claimed task %s (%s)", args.worker_id, task.id, task.repository_url)
        print(json.dumps({"claimed": True, "task_id": str(task.id), "worker_id": args.worker_id}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
