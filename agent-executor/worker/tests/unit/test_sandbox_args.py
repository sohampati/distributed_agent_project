"""The docker create command: every isolation flag present, nothing leaked in. No Docker needed."""

from __future__ import annotations

import pytest

from agent_worker import sandbox
from agent_worker.sandbox import SANDBOX_LABEL, SandboxConfig, docker_create_args

VOLUME = "agent-disk-abc"


def args_for(**overrides) -> list[str]:
    config = SandboxConfig(image="agent-sandbox-stub:test", memory="512m", cpus=1.5, pids_limit=128, **overrides)
    return docker_create_args(config, name="agent-sandbox-abc", volume=VOLUME)


def test_runs_a_named_labelled_container():
    args = args_for()

    assert args[:2] == ["docker", "create"]
    assert "--name=agent-sandbox-abc" in args
    assert f"--label={SANDBOX_LABEL}=1" in args


@pytest.mark.parametrize("flag", [
    "--network=none",                        # no network at all
    "--cap-drop=ALL",                        # no Linux capabilities
    "--security-opt=no-new-privileges",      # setuid binaries can't escalate
    "--read-only",                           # root filesystem is read-only...
    "--memory=512m",
    "--memory-swap=512m",                    # ...no swap beyond the memory limit
    "--cpus=1.5",
    "--pids-limit=128",                      # fork bombs stop here
])
def test_isolation_flags(flag):
    assert flag in args_for()


def test_workspace_is_the_task_disk_and_nothing_from_the_host_is_mounted():
    args = args_for()

    assert "--workdir=/workspace" in args
    assert any(a.startswith("--tmpfs=/tmp:") for a in args)
    # The only mount is the task's own fixed-size disk volume: no bind mounts of host paths at all.
    assert [a for a in args if a.startswith(("--volume", "--mount", "-v"))] == [
        f"--mount=type=volume,src={VOLUME},dst=/workspace,volume-nocopy"]


def test_runs_as_the_non_root_host_user(monkeypatch):
    monkeypatch.setattr(sandbox.os, "getuid", lambda: 501)
    monkeypatch.setattr(sandbox.os, "getgid", lambda: 20)

    assert "--user=501:20" in args_for()


def test_refuses_to_run_the_sandbox_as_root(monkeypatch):
    monkeypatch.setattr(sandbox.os, "getuid", lambda: 0)

    with pytest.raises(ValueError, match="root"):
        args_for()


def test_passes_only_the_prompt_and_home_into_the_environment(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret_value")
    monkeypatch.setenv("PGPASSWORD", "db_secret_value")

    args = args_for()

    # The prompt's value is taken from the docker client's environment, so it never appears in argv.
    assert [a for a in args if a.startswith(("--env", "-e"))] == ["--env=TASK_PROMPT", "--env=HOME=/tmp"]
    assert not any("secret_value" in a for a in args)
    assert not any("--env-file" in a for a in args)


def test_never_privileged_and_never_given_the_docker_socket():
    args = args_for()

    assert "--privileged" not in args
    assert not any("docker.sock" in a for a in args)


def test_image_comes_last_with_optional_command():
    assert args_for()[-1] == "agent-sandbox-stub:test"
    assert args_for(command=("sh", "-c", "id -u"))[-4:] == ["agent-sandbox-stub:test", "sh", "-c", "id -u"]
