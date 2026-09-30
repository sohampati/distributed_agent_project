"""Claim → clone → sandbox → record the outcome, with a fake sandbox and fake git (no Docker, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_worker.claim import claim_next_task
from agent_worker.executor import MAX_ERROR_CHARS, MAX_RESULT_CHARS, execute_task
from agent_worker.repo import CloneError, Workspace
from agent_worker.sandbox import SandboxResult
from tests.helpers import PUBLIC_REPO, insert_task, task_row


class FakeSandbox:
    def __init__(self, result: SandboxResult | None = None, error: Exception | None = None):
        self.result = result or SandboxResult(exit_code=0, output="ok", timed_out=False)
        self.error = error
        self.calls: list[tuple[Path, str]] = []

    def run(self, workspace: Path, prompt: str) -> SandboxResult:
        self.calls.append((workspace, prompt))
        if self.error:
            raise self.error
        return self.result


class FakeGit:
    def __init__(self, patch: str = "diff --git a/NOTES.md b/NOTES.md\n+done\n", clone_error: Exception | None = None):
        self.patch = patch
        self.clone_error = clone_error
        self.cloned: list[tuple[str, str | None]] = []

    def clone(self, url: str, dest_root: Path, token: str | None = None, timeout: float = 120) -> Workspace:
        self.cloned.append((url, token))
        if self.clone_error:
            raise self.clone_error
        (dest_root / "repo").mkdir(parents=True)
        (dest_root / "git").mkdir()
        return Workspace(root=dest_root, work_tree=dest_root / "repo", git_dir=dest_root / "git")

    def diff(self, workspace: Workspace) -> str:
        return self.patch


@pytest.fixture
def task(conn):
    insert_task(conn, prompt="Add a health endpoint")
    return claim_next_task(conn, "worker-1")


@pytest.fixture
def workspace_root(tmp_path) -> Path:
    return tmp_path / "workspaces"


def run(task, conn, workspace_root, sandbox=None, git=None, token=None):
    git = git or FakeGit()
    sandbox = sandbox or FakeSandbox()
    outcome = execute_task(task, conn=conn, worker_id="worker-1", sandbox=sandbox, workspace_root=workspace_root,
                           token=token, clone=git.clone, diff=git.diff)
    return outcome, sandbox, git


def test_success_records_the_diff(task, conn, workspace_root):
    outcome, sandbox, git = run(task, conn, workspace_root, token="ghp_x")

    assert outcome.status == "SUCCEEDED"
    assert git.cloned == [(PUBLIC_REPO, "ghp_x")]
    workspace, prompt = sandbox.calls[0]
    assert workspace.name == "repo" and prompt == "Add a health endpoint"
    row = task_row(conn, task.id)
    assert (row["status"], row["result"], row["error"]) == ("SUCCEEDED", git.patch, None)


def test_agent_that_changes_nothing_still_succeeds_with_empty_result(task, conn, workspace_root):
    outcome, _, _ = run(task, conn, workspace_root, git=FakeGit(patch=""))

    assert outcome.status == "SUCCEEDED"
    assert task_row(conn, task.id)["result"] == ""


def test_nonzero_exit_fails_with_exit_code_and_output(task, conn, workspace_root):
    sandbox = FakeSandbox(SandboxResult(exit_code=3, output="Traceback: boom", timed_out=False))

    outcome, _, _ = run(task, conn, workspace_root, sandbox=sandbox)

    assert outcome.status == "FAILED"
    row = task_row(conn, task.id)
    assert row["status"] == "FAILED"
    assert "exited with code 3" in row["error"] and "Traceback: boom" in row["error"]
    assert row["result"] is None


def test_timeout_fails_with_timeout_message(task, conn, workspace_root):
    sandbox = FakeSandbox(SandboxResult(exit_code=None, output="working...", timed_out=True))

    outcome, _, _ = run(task, conn, workspace_root, sandbox=sandbox)

    assert outcome.status == "FAILED"
    assert "timed out" in task_row(conn, task.id)["error"]


def test_clone_failure_fails_without_running_the_sandbox(task, conn, workspace_root):
    git = FakeGit(clone_error=CloneError("repository not found"))

    outcome, sandbox, _ = run(task, conn, workspace_root, git=git)

    assert outcome.status == "FAILED"
    assert sandbox.calls == []
    assert "clone failed" in task_row(conn, task.id)["error"]
    assert "repository not found" in task_row(conn, task.id)["error"]


def test_unexpected_error_fails_the_task_instead_of_leaving_it_running(task, conn, workspace_root):
    sandbox = FakeSandbox(error=RuntimeError("docker daemon went away"))

    outcome, _, _ = run(task, conn, workspace_root, sandbox=sandbox)

    assert outcome.status == "FAILED"
    row = task_row(conn, task.id)
    assert row["status"] == "FAILED"
    assert "RuntimeError" in row["error"] and "docker daemon went away" in row["error"]


@pytest.mark.parametrize("scenario", ["success", "failure", "timeout", "clone_error", "crash"])
def test_workspace_is_always_removed(task, conn, workspace_root, scenario):
    sandbox = {
        "failure": FakeSandbox(SandboxResult(exit_code=1, output="", timed_out=False)),
        "timeout": FakeSandbox(SandboxResult(exit_code=None, output="", timed_out=True)),
        "crash": FakeSandbox(error=RuntimeError("boom")),
    }.get(scenario)
    git = FakeGit(clone_error=CloneError("nope")) if scenario == "clone_error" else None

    run(task, conn, workspace_root, sandbox=sandbox, git=git)

    assert not workspace_root.exists() or list(workspace_root.iterdir()) == []


def test_failure_output_keeps_the_end_of_long_logs(task, conn, workspace_root):
    output = "early noise\n" * 10_000 + "the actual error at the end"
    sandbox = FakeSandbox(SandboxResult(exit_code=1, output=output, timed_out=False))

    run(task, conn, workspace_root, sandbox=sandbox)

    error = task_row(conn, task.id)["error"]
    assert len(error) <= MAX_ERROR_CHARS + 500  # room for the header line
    assert error.endswith("the actual error at the end")
    assert "truncated" in error


def test_oversized_diff_is_truncated_with_a_marker(task, conn, workspace_root):
    git = FakeGit(patch="+x\n" * (MAX_RESULT_CHARS // 3 + 1000))

    outcome, _, _ = run(task, conn, workspace_root, git=git)

    result = task_row(conn, task.id)["result"]
    assert outcome.status == "SUCCEEDED"
    assert len(result) <= MAX_RESULT_CHARS + 500
    assert "truncated" in result
