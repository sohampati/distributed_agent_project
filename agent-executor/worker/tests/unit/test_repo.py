"""Cloning and diffing, against a local git repository (no network)."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from agent_worker import repo
from agent_worker.repo import CloneError, clone, diff


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A local repository with two committed files."""
    path = tmp_path / "origin"
    path.mkdir()
    git = ["git", "-C", str(path), "-c", "user.name=test", "-c", "user.email=test@example.com"]
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "README.md").write_text("hello\n")
    (path / "delete_me.txt").write_text("bye\n")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    return path


def test_clone_checks_out_files_with_git_dir_outside_the_work_tree(origin, tmp_path):
    ws = clone(origin.as_uri(), tmp_path / "task-1")

    assert (ws.work_tree / "README.md").read_text() == "hello\n"
    # The sandbox only sees work_tree; with no .git there it can't plant hooks or config that the
    # worker's own git commands would later execute on the host.
    assert not (ws.work_tree / ".git").exists()
    assert (ws.git_dir / "HEAD").exists()
    assert ws.work_tree.is_relative_to(ws.root) and ws.git_dir.is_relative_to(ws.root)
    assert not ws.git_dir.is_relative_to(ws.work_tree)


def test_diff_is_empty_when_nothing_changed(origin, tmp_path):
    ws = clone(origin.as_uri(), tmp_path / "task-1")

    assert diff(ws) == ""


def test_diff_includes_modified_new_and_deleted_files(origin, tmp_path):
    ws = clone(origin.as_uri(), tmp_path / "task-1")
    (ws.work_tree / "README.md").write_text("hello\nworld\n")
    (ws.work_tree / "NEW.md").write_text("brand new\n")
    (ws.work_tree / "delete_me.txt").unlink()

    patch = diff(ws)

    assert "+world" in patch
    assert "+brand new" in patch
    assert "deleted file mode" in patch and "-bye" in patch


def test_clone_failure_raises_clone_error(tmp_path):
    with pytest.raises(CloneError):
        clone((tmp_path / "does-not-exist").as_uri(), tmp_path / "task-1")


def test_token_goes_in_the_environment_never_in_argv(origin, tmp_path, monkeypatch):
    calls = []
    real_run = subprocess.run

    def spy(args, **kwargs):
        calls.append((list(args), kwargs.get("env") or {}))
        return real_run(args, **kwargs)

    monkeypatch.setattr(repo.subprocess, "run", spy)

    clone(origin.as_uri(), tmp_path / "task-1", token="ghp_secret_value")

    assert calls, "clone did not run git"
    assert not any("ghp_secret_value" in arg for args, _ in calls for arg in args)
    clone_env = calls[0][1]
    expected = base64.b64encode(b"x-access-token:ghp_secret_value").decode()
    assert expected in "".join(v for k, v in clone_env.items() if k.startswith("GIT_CONFIG_VALUE_"))
    assert clone_env.get("GIT_TERMINAL_PROMPT") == "0"  # never hang waiting for a password
