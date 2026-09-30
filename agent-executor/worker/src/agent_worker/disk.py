"""Per-task fixed-size disk: an ext4 image on a loop device, exposed to the sandbox as a Docker volume.

Docker can't cap a volume's size on Colima's filesystem, so each task gets its own small filesystem instead;
when it's full, writes fail with "No space left on device". The image lives inside the Docker host (the VM),
never on the Mac. Creating and destroying it needs a privileged helper container that only runs the fixed
commands below, built from validated values; no task input ever reaches it.
"""

from __future__ import annotations

import logging
import os
import posixpath
import re
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

# On the Docker host (inside the Colima VM), not on the Mac.
DISK_DIR = "/var/lib/agent-worker/disks"
DISK_LABEL = "agent-worker.sandbox"

_SIZE = re.compile(r"[1-9][0-9]*[kmg]", re.IGNORECASE)
_LOOP_DEVICE = re.compile(r"/dev/loop[0-9]+")
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


@dataclass(frozen=True)
class TaskDisk:
    volume: str       # Docker volume name, mounted into the sandbox
    image_path: str   # ext4 image file on the Docker host
    loop_device: str  # e.g. /dev/loop3


def validate_size(size: str) -> str:
    """Accepts sizes like 512m or 2g; returns the value as passed to truncate (e.g. 512M)."""
    if not _SIZE.fullmatch(size):
        raise ValueError(f"invalid disk size {size!r}; use e.g. 512m or 2g")
    return size.upper()


def helper_args(helper_image: str, script: str) -> list[str]:
    """Runs ``script`` in the privileged helper: offline, with only the disk directory mounted."""
    return ["docker", "run", "--rm", "--privileged", "--network=none", f"--volume={DISK_DIR}:{DISK_DIR}",
            helper_image, "sh", "-c", script]


def create_script(image_path: str, size: str, uid: int, gid: int) -> str:
    """Creates a sparse image, formats it owned by the sandbox user, and attaches it; prints the loop device."""
    size = validate_size(size)
    _check_image_path(image_path)
    return "\n".join([
        "set -e",
        f"truncate -s {size} {image_path}",
        # No journal and no reserved blocks: it's a throwaway scratch disk, so every byte goes to the agent.
        f"mkfs.ext4 -q -F -m 0 -O ^has_journal -E root_owner={int(uid)}:{int(gid)} {image_path}",
        f"debugfs -w -R 'rmdir lost+found' {image_path} >/dev/null 2>&1",
        f"losetup --find --show {image_path}",
    ])


def volume_create_args(name: str, loop_device: str) -> list[str]:
    if not _LOOP_DEVICE.fullmatch(loop_device):
        raise ValueError(f"not a loop device: {loop_device!r}")
    return [
        "docker", "volume", "create",
        "--driver=local",
        "--opt=type=ext4",
        f"--opt=device={loop_device}",
        "--opt=o=nosuid,nodev",  # no setuid binaries or device files from the task's disk
        f"--label={DISK_LABEL}=1",
        name,
    ]


def create_disk(name: str, size: str, helper_image: str) -> TaskDisk:
    """Creates the task's disk and its Docker volume. On failure, anything half-created is removed."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"invalid disk name {name!r}")
    image_path = f"{DISK_DIR}/{name}.img"
    created = subprocess.run(helper_args(helper_image, create_script(image_path, size, os.getuid(), os.getgid())),
                             capture_output=True, text=True)
    loop_device = created.stdout.strip().splitlines()[-1] if created.stdout.strip() else ""
    disk = TaskDisk(volume=name, image_path=image_path, loop_device=loop_device)
    if created.returncode != 0 or not _LOOP_DEVICE.fullmatch(loop_device):
        destroy_disk(disk, helper_image)
        raise RuntimeError(f"could not create task disk: {created.stderr.strip() or created.stdout.strip()}")

    volume = subprocess.run(volume_create_args(name, loop_device), capture_output=True, text=True)
    if volume.returncode != 0:
        destroy_disk(disk, helper_image)
        raise RuntimeError(f"could not create disk volume: {volume.stderr.strip()}")
    return disk


def destroy_disk(disk: TaskDisk, helper_image: str) -> None:
    """Removes the volume, detaches the loop device and deletes the image. Best effort and idempotent."""
    subprocess.run(["docker", "volume", "rm", "--force", disk.volume], capture_output=True)
    _check_image_path(disk.image_path)
    # Detach whatever loop device backs this image (not a device number we might have recorded wrongly).
    script = (f'for dev in $(losetup -j {disk.image_path} | cut -d: -f1); do losetup -d "$dev"; done; '
              f"rm -f {disk.image_path}")
    result = subprocess.run(helper_args(helper_image, script), capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("could not fully remove disk %s: %s", disk.volume, result.stderr.strip())


def _check_image_path(image_path: str) -> None:
    if posixpath.dirname(posixpath.normpath(image_path)) != DISK_DIR or not image_path.endswith(".img") \
            or not _NAME.fullmatch(posixpath.basename(image_path)[:-len(".img")]):
        raise ValueError(f"disk image must be a plain file name in {DISK_DIR}: {image_path!r}")
