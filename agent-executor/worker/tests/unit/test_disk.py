"""The per-task disk's commands: the privileged helper only ever runs fixed, validated commands. No Docker needed."""

from __future__ import annotations

import pytest

from agent_worker.disk import DISK_DIR, DISK_LABEL, create_script, helper_args, validate_size, volume_create_args


@pytest.mark.parametrize("size, expected", [("512m", "512M"), ("2g", "2G"), ("64M", "64M"), ("1024k", "1024K")])
def test_accepts_plain_sizes(size, expected):
    assert validate_size(size) == expected


@pytest.mark.parametrize("size", [
    "", "0g", "2", "2gb", "-1g", "1.5g", "2t",
    "1g; rm -rf /",          # the size ends up in a shell script run by a privileged container
    "1g $(reboot)", "1g\n", "`id`g",
])
def test_rejects_anything_else(size):
    with pytest.raises(ValueError):
        validate_size(size)


def test_helper_runs_offline_with_only_the_disk_directory_mounted():
    args = helper_args("agent-sandbox-disk-helper:test", "echo hi")

    assert args[:3] == ["docker", "run", "--rm"]
    assert "--privileged" in args  # attaching a loop device needs it; the sandbox itself never is
    assert "--network=none" in args
    assert [a for a in args if a.startswith(("--volume", "-v", "--mount"))] == [f"--volume={DISK_DIR}:{DISK_DIR}"]
    assert args[-4:] == ["agent-sandbox-disk-helper:test", "sh", "-c", "echo hi"]


def test_create_script_formats_owns_and_attaches_the_image():
    script = create_script(f"{DISK_DIR}/agent-disk-abc.img", "512m", uid=501, gid=20)

    assert f"truncate -s 512M {DISK_DIR}/agent-disk-abc.img" in script
    assert "mkfs.ext4" in script and "root_owner=501:20" in script  # the non-root sandbox user owns /workspace
    assert "rmdir lost+found" in script                             # otherwise it would appear in every diff
    assert script.rstrip().endswith(f"losetup --find --show {DISK_DIR}/agent-disk-abc.img")


def test_create_script_rejects_bad_sizes_and_paths_outside_the_disk_directory():
    with pytest.raises(ValueError):
        create_script(f"{DISK_DIR}/x.img", "1g; reboot", uid=501, gid=20)
    with pytest.raises(ValueError):
        create_script("/etc/passwd", "1g", uid=501, gid=20)
    with pytest.raises(ValueError):
        create_script(f"{DISK_DIR}/../../etc/x.img", "1g", uid=501, gid=20)


def test_volume_is_the_loop_device_mounted_nosuid_nodev_and_labelled():
    args = volume_create_args("agent-disk-abc", "/dev/loop3")

    assert args[:3] == ["docker", "volume", "create"]
    assert "--driver=local" in args
    assert "--opt=type=ext4" in args
    assert "--opt=device=/dev/loop3" in args
    assert "--opt=o=nosuid,nodev" in args  # no setuid binaries or device files from the task's disk
    assert f"--label={DISK_LABEL}=1" in args
    assert args[-1] == "agent-disk-abc"


@pytest.mark.parametrize("device", ["/dev/sda", "/dev/loop", "/dev/loop3; reboot", "loop3"])
def test_volume_only_accepts_loop_devices(device):
    with pytest.raises(ValueError):
        volume_create_args("agent-disk-abc", device)
