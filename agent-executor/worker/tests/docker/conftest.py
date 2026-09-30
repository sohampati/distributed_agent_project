from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_worker.disk import DISK_DIR, DISK_LABEL
from agent_worker.sandbox import SANDBOX_LABEL
from tests.helpers import build_disk_helper_image, build_stub_image, docker_available


def pytest_collection_modifyitems(items):
    here = Path(__file__).parent
    for item in items:
        if Path(item.fspath).is_relative_to(here):
            item.add_marker(pytest.mark.docker)


@pytest.fixture(scope="session", autouse=True)
def require_docker():
    if not docker_available():
        pytest.skip("Docker is not running (start it with: colima start)")


@pytest.fixture(scope="session")
def stub_image() -> str:
    return build_stub_image()


@pytest.fixture(scope="session")
def disk_helper_image() -> str:
    return build_disk_helper_image()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A workspace in the system temp dir. Colima does NOT share that with its VM, so these tests also prove
    files reach the sandbox by copying, not by mounting a host directory."""
    path = tmp_path / "repo"
    path.mkdir()
    (path / "README.md").write_text("hello\n")
    return path


def _docker(*args: str) -> list[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout.split()


@pytest.fixture(autouse=True)
def no_leftovers(require_docker, disk_helper_image) -> Iterator[None]:
    """After every test: no sandbox container, disk volume, disk image or attached loop device may remain."""
    yield
    containers = _docker("ps", "-aq", "--filter", f"label={SANDBOX_LABEL}")
    volumes = _docker("volume", "ls", "-q", "--filter", f"label={DISK_LABEL}")
    state = subprocess.run(
        ["docker", "run", "--rm", "--privileged", "--network=none", f"--volume={DISK_DIR}:{DISK_DIR}",
         disk_helper_image, "sh", "-c", f"ls {DISK_DIR}; losetup --list --noheadings --output BACK-FILE | grep {DISK_DIR} || true"],
        capture_output=True, text=True, check=True,
    ).stdout.split()

    # Clean up so one failure doesn't cascade into every following test, then report.
    if containers:
        subprocess.run(["docker", "rm", "-f", *containers], capture_output=True)
    if volumes:
        subprocess.run(["docker", "volume", "rm", "-f", *volumes], capture_output=True)
    if state:
        subprocess.run(
            ["docker", "run", "--rm", "--privileged", "--network=none", f"--volume={DISK_DIR}:{DISK_DIR}",
             disk_helper_image, "sh", "-c",
             f"for f in {DISK_DIR}/*; do losetup -j \"$f\" | cut -d: -f1 | xargs -r losetup -d; rm -f \"$f\"; done"],
            capture_output=True)
    assert not (containers or volumes or state), (
        f"left behind: containers={containers} volumes={volumes} disk images/loop devices={state}")
