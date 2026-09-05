#!/usr/bin/env python3
"""Mount/unmount the floppy drive as media appears and disappears.

Floppy insert/eject is a capacity change on a fixed USB device, not a USB
hotplug event, so the device node stays put and we poll its size. Runs as root
via systemd so the mount lives in the host namespace and is visible to the
unprivileged ``floppify`` service.
"""

import logging
import os
import subprocess
import time

DEVICE = os.environ.get("FLOPPIFY_FLOPPY_DEVICE", "/dev/sda")
MOUNT_POINT = os.environ.get("FLOPPIFY_FLOPPY_MOUNT", "/mnt/floppify")
POLL_SECONDS = float(os.environ.get("FLOPPIFY_FLOPPY_POLL", "1.0"))
FS_TYPE = os.environ.get("FLOPPIFY_FLOPPY_FSTYPE", "vfat")

LOGGER = logging.getLogger("floppify-mounter")


def media_present() -> bool:
    """Return whether the floppy currently holds media."""
    sysfs_size = f"/sys/class/block/{os.path.basename(DEVICE)}/size"
    try:
        with open(sysfs_size, encoding="utf-8") as handle:
            return int(handle.read().strip()) > 0
    except (FileNotFoundError, ValueError, OSError):
        return False


def is_mounted() -> bool:
    """Return whether the mount point currently holds a filesystem."""
    result = subprocess.run(
        ["findmnt", "-n", "-o", "SOURCE", MOUNT_POINT],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


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


def main() -> None:
    """Poll forever, keeping the floppy mounted exactly while media is present."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    LOGGER.info("watching %s -> %s", DEVICE, MOUNT_POINT)
    while True:
        try:
            if media_present() and not is_mounted():
                mount()
            elif not media_present() and is_mounted():
                unmount()
        except Exception:
            LOGGER.exception("mounter iteration failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
