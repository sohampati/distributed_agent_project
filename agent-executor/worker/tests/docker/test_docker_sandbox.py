"""Real containers: the sandbox really is isolated, bounded and cleaned up."""

from __future__ import annotations

import os
import time
from pathlib import Path

from agent_worker.sandbox import DockerSandbox, SandboxConfig
from tests.helpers import DISK_HELPER_TEST_IMAGE  # built once per session by conftest


def sandbox(image: str, *command: str, **config) -> DockerSandbox:
    return DockerSandbox(SandboxConfig(image=image, command=command or None, timeout_seconds=config.pop("timeout", 30),
                                       disk_helper_image=DISK_HELPER_TEST_IMAGE, **config))


# ---- the stub agent -----------------------------------------------------------------------------------------------


def test_stub_agent_edits_the_workspace(stub_image, workspace):
    result = sandbox(stub_image).run(workspace, "Add a health endpoint")

    assert (result.exit_code, result.timed_out) == (0, False), result.output
    assert "Task: Add a health endpoint" in (workspace / "AGENT_NOTES.md").read_text()
    assert "wrote AGENT_NOTES.md" in result.output


def test_prompt_is_passed_through_exactly(stub_image, workspace):
    prompt = "Fix the bug in `main.py`; don't touch \"tests\" & keep $HOME\nsecond line"

    sandbox(stub_image).run(workspace, prompt)

    assert f"Task: {prompt}" in (workspace / "AGENT_NOTES.md").read_text()


def test_failing_agent_reports_exit_code_and_output(stub_image, workspace):
    result = sandbox(stub_image).run(workspace, "please [stub:fail]")

    assert result.exit_code == 1
    assert "failing as requested" in result.output
    assert result.timed_out is False


# ---- limits -------------------------------------------------------------------------------------------------------


def test_timeout_kills_the_container(stub_image, workspace):
    start = time.monotonic()

    result = sandbox(stub_image, timeout=2).run(workspace, "[stub:sleep]")

    assert result.timed_out is True
    assert result.exit_code is None
    assert time.monotonic() - start < 15  # killed, not left to sleep for an hour
    # no_leftover_containers checks the container is gone


def test_memory_limit_is_enforced(workspace):
    # tail buffers a newline-free stream in memory, so this tries to hold ~200 MB.
    result = sandbox("alpine:3.20", "sh", "-c", "head -c 200m /dev/zero | tail > /dev/null", memory="64m").run(
        workspace, "")

    assert result.exit_code == 137, result.output  # SIGKILL from the OOM killer


def test_process_limit_is_enforced(workspace):
    result = sandbox("alpine:3.20", "sh", "-c", "for i in $(seq 1 100); do sleep 5 & done; wait",
                     pids_limit=20, timeout=20).run(workspace, "")

    assert result.exit_code != 0
    assert "can't fork" in result.output or "Resource temporarily unavailable" in result.output, result.output


# ---- isolation ----------------------------------------------------------------------------------------------------


def test_no_network_access(workspace):
    result = sandbox("alpine:3.20", "sh", "-c", "wget -q -T 5 -O /dev/null https://github.com && echo REACHED").run(
        workspace, "")

    assert result.exit_code != 0
    assert "REACHED" not in result.output


def test_runs_as_non_root(workspace):
    result = sandbox("alpine:3.20", "id", "-u").run(workspace, "")

    assert result.exit_code == 0
    assert result.output.strip() != "0"


def test_only_workspace_and_tmp_are_writable(workspace):
    script = (
        "touch /etc/pwned 2>/dev/null && echo ROOTFS-WRITABLE; "
        "touch /workspace/ok && echo workspace-ok; "
        "touch /tmp/ok && echo tmp-ok"
    )
    result = sandbox("alpine:3.20", "sh", "-c", script).run(workspace, "")

    assert "ROOTFS-WRITABLE" not in result.output
    assert "workspace-ok" in result.output and "tmp-ok" in result.output
    assert (workspace / "ok").exists()


def test_secrets_from_the_worker_environment_are_not_visible(workspace, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret_value")
    monkeypatch.setenv("PGPASSWORD", "db_secret_value")

    result = sandbox("alpine:3.20", "env").run(workspace, "the prompt")

    assert "secret_value" not in result.output
    assert "TASK_PROMPT=the prompt" in result.output


def test_workspace_has_no_git_metadata_to_tamper_with(workspace):
    result = sandbox("alpine:3.20", "sh", "-c", "ls -a /workspace").run(workspace, "")

    assert ".git" not in result.output.split()


def test_missing_image_is_a_failure_not_a_hang(workspace):
    result = sandbox("agent-sandbox-does-not-exist:nope", timeout=60).run(workspace, "")

    assert result.exit_code not in (0, None)
    assert result.timed_out is False


# ---- the task's disk ----------------------------------------------------------------------------------------------


def test_disk_size_limit_is_enforced(workspace):
    script = "dd if=/dev/zero of=/workspace/big bs=1M count=64; echo dd-exit=$?; df -k /workspace | tail -1"
    result = sandbox("alpine:3.20", "sh", "-c", script, disk_size="32m").run(workspace, "")

    assert "No space left on device" in result.output, result.output
    assert "dd-exit=0" not in result.output
    # What made it to disk (and was copied back) is capped by the disk, not the 64 MB requested.
    assert (workspace / "big").stat().st_size < 32 * 1024 * 1024


def test_all_changes_are_copied_back(workspace):
    (workspace / "delete_me.txt").write_text("bye\n")
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("print('v1')\n")
    script = (
        "echo world >> README.md && rm delete_me.txt && echo 'print(\"v2\")' > src/app.py "
        "&& mkdir -p docs && echo new > docs/NEW.md"
    )

    result = sandbox("alpine:3.20", "sh", "-c", script).run(workspace, "")

    assert result.exit_code == 0, result.output
    assert (workspace / "README.md").read_text() == "hello\nworld\n"
    assert not (workspace / "delete_me.txt").exists()
    assert (workspace / "src" / "app.py").read_text() == 'print("v2")\n'
    assert (workspace / "docs" / "NEW.md").read_text() == "new\n"
    # Filesystem internals don't leak into the workspace (they'd show up in every diff).
    assert not (workspace / "lost+found").exists()


def test_copied_back_files_belong_to_the_worker_user(workspace):
    sandbox("alpine:3.20", "sh", "-c", "echo x > created.txt").run(workspace, "")

    for path in [workspace / "created.txt", workspace / "README.md"]:
        assert path.stat().st_uid == os.getuid()


def test_host_filesystem_is_not_mounted(workspace):
    result = sandbox("alpine:3.20", "cat", "/proc/mounts").run(workspace, "")

    assert result.exit_code == 0
    assert str(Path.home()) not in result.output
    assert "/Users" not in result.output
    assert str(workspace) not in result.output
    # /workspace is its own small filesystem (the task's loop device), not a share from the host.
    workspace_mount = next(line for line in result.output.splitlines() if " /workspace " in line)
    assert workspace_mount.startswith("/dev/loop") and "ext4" in workspace_mount
    assert "nosuid" in workspace_mount and "nodev" in workspace_mount


def test_nothing_is_copied_back_after_a_timeout(stub_image, workspace):
    result = sandbox(stub_image, timeout=2).run(workspace, "[stub:sleep]")

    assert result.timed_out
    assert sorted(p.name for p in workspace.iterdir()) == ["README.md"]
