from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from agent_worker.disk import create_disk, destroy_disk

# Every sandbox container carries this label, so leftovers are easy to find: docker ps -a --filter label=...
SANDBOX_LABEL = "agent-worker.sandbox"


@dataclass(frozen=True)
class SandboxConfig:
    image: str
    timeout_seconds: float = 600
    memory: str = "2g"
    cpus: float = 1.0
    pids_limit: int = 256
    disk_size: str = "2g"  # the agent's /workspace is a filesystem of exactly this size
    disk_helper_image: str = "agent-sandbox-disk-helper:latest"
    command: tuple[str, ...] | None = None  # overrides the image's entrypoint arguments (used by tests)


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int | None  # None when killed on timeout
    output: str            # combined stdout and stderr
    timed_out: bool


def docker_create_args(config: SandboxConfig, *, name: str, volume: str) -> list[str]:
    """The ``docker create`` command for one sandbox whose /workspace is the task's disk volume."""
    uid, gid = os.getuid(), os.getgid()
    if uid == 0:
        raise ValueError("refusing to run the sandbox as root; run the worker as a regular user")

    return [
        "docker", "create",
        f"--name={name}",
        f"--label={SANDBOX_LABEL}=1",
        # Isolation
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        # The host user's uid: non-root, and files copied back to the workspace stay owned by the worker.
        f"--user={uid}:{gid}",
        "--read-only",
        "--tmpfs=/tmp:rw,size=256m",
        # The task's own fixed-size filesystem (see disk.py). Nothing from the host is mounted.
        # volume-nocopy: otherwise Docker "populates" the empty volume from the image and resets its root to root:root.
        f"--mount=type=volume,src={volume},dst=/workspace,volume-nocopy",
        "--workdir=/workspace",
        # Resource limits
        f"--memory={config.memory}",
        f"--memory-swap={config.memory}",
        f"--cpus={config.cpus}",
        f"--pids-limit={config.pids_limit}",
        # Environment: nothing from the worker leaks in. TASK_PROMPT's value comes from the docker client's
        # environment (see DockerSandbox.run) so the prompt isn't visible in the host's process list.
        "--env=TASK_PROMPT",
        "--env=HOME=/tmp",
        config.image,
        *(config.command or ()),
    ]


class DockerSandbox:
    """Runs one task in a fresh, isolated container via the docker CLI (which honours docker contexts, e.g. Colima).

    The workspace is copied onto the task's own fixed-size disk, the agent runs, and the disk's contents are copied
    back over the workspace. The container never sees a host directory.
    """

    def __init__(self, config: SandboxConfig):
        self.config = config

    def run(self, workspace: Path, prompt: str) -> SandboxResult:
        suffix = uuid.uuid4().hex[:12]
        name = f"agent-sandbox-{suffix}"
        disk = create_disk(f"agent-disk-{suffix}", self.config.disk_size, self.config.disk_helper_image)
        # Only what the docker CLI needs to find the daemon, plus the prompt it forwards into the container.
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT",
                                                            "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY")}
        env["TASK_PROMPT"] = prompt
        try:
            created = subprocess.run(docker_create_args(self.config, name=name, volume=disk.volume),
                                     env=env, capture_output=True, text=True)
            if created.returncode != 0:  # e.g. the image doesn't exist
                return SandboxResult(exit_code=created.returncode, output=created.stdout + created.stderr,
                                     timed_out=False)
            # --archive keeps the files' uid/gid, i.e. the (non-root) sandbox user can edit them.
            _docker("cp", "--archive", f"{workspace}/.", f"{name}:/workspace")

            try:
                started = subprocess.run(["docker", "start", "--attach", name], stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, timeout=self.config.timeout_seconds)
            except subprocess.TimeoutExpired as e:
                partial = e.output.decode(errors="replace") if isinstance(e.output, bytes) else (e.output or "")
                return SandboxResult(exit_code=None, output=partial, timed_out=True)

            _copy_back(name, workspace)
            return SandboxResult(exit_code=started.returncode, output=started.stdout, timed_out=False)
        finally:
            # Killing the docker client (on timeout) doesn't stop the container; rm --force kills and removes it.
            subprocess.run(["docker", "rm", "--force", name], capture_output=True)
            destroy_disk(disk, self.config.disk_helper_image)


def _copy_back(name: str, workspace: Path) -> None:
    """Replaces the workspace's contents with the disk's, so deletions come back too (git metadata lives elsewhere)."""
    for child in workspace.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    # If this fails the workspace is incomplete; raising makes the task FAILED rather than recording a bogus diff.
    _docker("cp", f"{name}:/workspace/.", str(workspace))


def _docker(*args: str) -> None:
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr.strip()}")
