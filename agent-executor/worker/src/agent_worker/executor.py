from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psycopg

from agent_worker import repo
from agent_worker.claim import ClaimedTask
from agent_worker.complete import complete_task, fail_task
from agent_worker.sandbox import SandboxResult

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 1_000_000  # a diff larger than this is truncated
MAX_ERROR_CHARS = 20_000      # failure output keeps the last this-many characters


class Sandbox(Protocol):
    def run(self, workspace: Path, prompt: str) -> SandboxResult: ...


@dataclass(frozen=True)
class ExecutionOutcome:
    status: str  # "SUCCEEDED" or "FAILED"
    result: str | None
    error: str | None


def execute_task(
    task: ClaimedTask,
    *,
    conn: psycopg.Connection,
    worker_id: str,
    sandbox: Sandbox,
    workspace_root: Path,
    token: str | None = None,
    clone: Callable[..., repo.Workspace] = repo.clone,
    diff: Callable[[repo.Workspace], str] = repo.diff,
) -> ExecutionOutcome:
    """Runs a claimed task end to end and records SUCCEEDED or FAILED. Never leaves the task RUNNING on error."""
    task_root = workspace_root / str(task.id)
    try:
        outcome = _run(task, sandbox, task_root, token, clone, diff)
    except Exception as e:  # anything unexpected still ends the task, rather than stranding it RUNNING
        log.exception("task %s: worker error", task.id)
        outcome = ExecutionOutcome("FAILED", None, f"worker error: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(task_root, ignore_errors=True)

    if outcome.status == "SUCCEEDED":
        recorded = complete_task(conn, task.id, worker_id, outcome.result)
    else:
        recorded = fail_task(conn, task.id, worker_id, outcome.error)
    if not recorded:
        log.warning("task %s: outcome not recorded; %s no longer owns it", task.id, worker_id)
    return outcome


def _run(task, sandbox, task_root, token, clone, diff) -> ExecutionOutcome:
    try:
        workspace = clone(task.repository_url, task_root, token=token)
    except repo.CloneError as e:
        return ExecutionOutcome("FAILED", None, f"clone failed: {e}")

    result = sandbox.run(workspace.work_tree, task.prompt)
    if result.timed_out:
        return ExecutionOutcome("FAILED", None, _with_output("sandbox timed out", result.output))
    if result.exit_code != 0:
        return ExecutionOutcome("FAILED", None, _with_output(f"sandbox exited with code {result.exit_code}",
                                                             result.output))
    return ExecutionOutcome("SUCCEEDED", _truncate_head(diff(workspace), MAX_RESULT_CHARS), None)


def _with_output(message: str, output: str) -> str:
    if not output:
        return message
    if len(output) > MAX_ERROR_CHARS:
        dropped = len(output) - MAX_ERROR_CHARS
        return f"{message}\n--- output (first {dropped} chars truncated) ---\n{output[-MAX_ERROR_CHARS:]}"
    return f"{message}\n--- output ---\n{output}"


def _truncate_head(text: str, limit: int) -> str:
    """Keeps the start of a diff (the file headers) and says how much was cut."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n[diff truncated: {len(text) - limit} more chars]\n"
