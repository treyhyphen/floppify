#!/usr/bin/env python3
"""Mount/unmount the floppy drive as media appears and disappears.

Floppy insert/eject is a capacity change on a fixed USB device, not a USB
hotplug event, and the kernel only re-checks media when the block device is
opened. We poll on a fast cycle and open the device each tick to force a media
re-check, then mount on insert and, on eject, unmount and notify the app to
stop playback immediately. Runs as root via systemd so the mount lives in the
host namespace and is visible to the unprivileged ``floppify`` service.
"""

import logging
import os
import subprocess
import time

DEVICE = os.environ.get("FLOPPIFY_FLOPPY_DEVICE", "/dev/sda")
MOUNT_POINT = os.environ.get("FLOPPIFY_FLOPPY_MOUNT", "/mnt/floppify")
POLL_SECONDS = float(os.environ.get("FLOPPIFY_FLOPPY_POLL", "0.4"))
FS_TYPE = os.environ.get("FLOPPIFY_FLOPPY_FSTYPE", "vfat")
APP_BASE_URL = os.environ.get("FLOPPIFY_APP_URL", "http://127.0.0.1:8000")

LOGGER = logging.getLogger("floppify-mounter")


def media_present() -> bool:
    """Return whether the floppy currently holds media.

    Opening the block device forces the SCSI layer to re-check media (an
    ``sd_open`` -> ``check_disk_change`` -> ``revalidate_disk`` cycle), so the
    sysfs size read afterwards reflects the current media state instead of a
    stale cached capacity.
    """
    try:
        fd = os.open(DEVICE, os.O_RDONLY | os.O_NONBLOCK)
        os.close(fd)
    except OSError:
        return False
    sysfs_size = f"/sys/class/block/{os.path.basename(DEVICE)}/size"
    try:
        with open(sysfs_size, encoding="utf-8") as handle:
            return int(handle.read().strip()) > 0
    except (FileNotFoundError, ValueError, OSError):
        return False


def is_mounted() -> bool:
    """Return whether the mount point currently holds a filesystem."""
    return os.path.ismount(MOUNT_POINT)


def mount() -> None:
    """Mount the floppy read-only at the configured mount point."""
    os.makedirs(MOUNT_POINT, exist_ok=True)
    result = subprocess.run(
        ["mount", "-t", FS_TYPE, "-o", "ro,noexec,nodev,nosuid", DEVICE, MOUNT_POINT],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        LOGGER.info("mounted %s at %s", DEVICE, MOUNT_POINT)
    else:
        LOGGER.warning("mount failed: %s", result.stderr.strip())


def unmount() -> None:
    """Unmount the floppy, tolerating an already-gone filesystem."""
    result = subprocess.run(
        ["umount", MOUNT_POINT], capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        LOGGER.info("unmounted %s", MOUNT_POINT)
    elif "not mounted" not in result.stderr:
        LOGGER.warning("unmount failed: %s", result.stderr.strip())


def notify_eject() -> None:
    """Tell the app to stop playback and clear its queue immediately."""
    try:
        result = subprocess.run(
            [
                "curl",
                "-fsS",
                "--max-time",
                "3",
                "--noproxy",
                "*",
                "-X",
                "POST",
                f"{APP_BASE_URL}/api/eject",
            ],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            LOGGER.info("notified app to stop playback")
        else:
            LOGGER.warning("eject notify failed: %s", result.stderr.decode().strip())
    except Exception:
        LOGGER.exception("eject notify failed")


def main() -> None:
    """Poll forever, keeping the floppy mounted exactly while media is present."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    LOGGER.info("watching %s -> %s (poll %.2fs)", DEVICE, MOUNT_POINT, POLL_SECONDS)
    while True:
        try:
            if media_present() and not is_mounted():
                mount()
            elif not media_present() and is_mounted():
                unmount()
                notify_eject()
        except Exception:
            LOGGER.exception("mounter iteration failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
