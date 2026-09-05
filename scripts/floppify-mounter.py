#!/usr/bin/env python3
"""Mount/unmount the floppy drive as media appears and disappears.

Floppy insert/eject is a capacity change on a fixed USB device, not a USB
hotplug event. USB Mass Storage is host-polled -- the drive (a CBI/UFI TEAC
floppy) has no way to push a media-change event to the kernel, and its eject
button is mechanical, so the kernel only discovers a change when a command is
sent. We therefore probe by opening the block device, which forces the SCSI
layer to re-check media.

To avoid needless chatter, we poll fast only while media is present (when an
eject could happen at any moment) and back off while idle. Runs as root via
systemd so the mount lives in the host namespace and is visible to the
unprivileged ``floppify`` service.
"""

import logging
import os
import subprocess
import time

DEVICE = os.environ.get("FLOPPIFY_FLOPPY_DEVICE", "/dev/sda")
MOUNT_POINT = os.environ.get("FLOPPIFY_FLOPPY_MOUNT", "/mnt/floppify")
# Poll interval while media is present (snappy eject detection).
POLL_SECONDS = float(os.environ.get("FLOPPIFY_FLOPPY_POLL", "0.3"))
# Poll interval while idle (no media) -- insert can tolerate a small delay.
IDLE_POLL_SECONDS = float(os.environ.get("FLOPPIFY_FLOPPY_POLL_IDLE", "1.5"))
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
    """Probe forever, mounting while media is present and unmounting on eject."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    LOGGER.info(
        "watching %s -> %s (poll %.2fs while present, %.2fs while idle)",
        DEVICE,
        MOUNT_POINT,
        POLL_SECONDS,
        IDLE_POLL_SECONDS,
    )
    while True:
        present = False
        try:
            present = media_present()
            if present and not is_mounted():
                mount()
            elif not present and is_mounted():
                unmount()
                notify_eject()
        except Exception:
            LOGGER.exception("mounter iteration failed")
        time.sleep(POLL_SECONDS if present else IDLE_POLL_SECONDS)


if __name__ == "__main__":
    main()
