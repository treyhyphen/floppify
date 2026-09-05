"""Floppy drive effects: mechanical seek noise for UI feedback and transitions.

The music is streamed, but the floppy drive can still produce its classic
seek/grind noise on demand by reading scattered sectors, which shuttles the
head across the disk. The app triggers this on transport controls and just
before a track ends to sell the illusion that audio is being read off the
floppy.
"""

import asyncio
import logging
import mmap
import os
import time
from typing import Protocol

LOGGER = logging.getLogger(__name__)

DEFAULT_DEVICE = "/dev/sda"
BLOCK_SIZE = 512
DEFAULT_SEEKS = 6
MIN_INTERVAL = 0.12
TRACK_END_WINDOW_MS = 1000


class Thumper(Protocol):
    """Minimal interface for a floppy thump trigger (duck-typed for tests)."""

    async def thump(self) -> None:
        """Fire a debounced seek-read."""
        ...


class FloppyThumper:
    """Trigger debounced floppy seek-reads to produce mechanical feedback noise."""

    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        seeks: int = DEFAULT_SEEKS,
        min_interval: float = MIN_INTERVAL,
    ) -> None:
        """Configure the floppy device, read count, and press-debounce window."""
        self.device = device
        self.seeks = seeks
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def thump(self) -> None:
        """Fire one seek-read off the event loop, debounced against rapid presses."""
        now = time.monotonic()
        if self._lock.locked() or now - self._last < self.min_interval:
            return
        async with self._lock:
            self._last = now
            await asyncio.to_thread(self._thump)

    def _thump(self) -> None:
        """Read scattered sectors to shuttle the drive head for audible feedback."""
        direct = getattr(os, "O_DIRECT", 0)
        try:
            fd = os.open(self.device, os.O_RDONLY | direct)
        except OSError as error:
            LOGGER.warning("Could not open floppy for tactile feedback: %s", error)
            return
        buffer = mmap.mmap(-1, 4096)
        try:
            try:
                size = os.lseek(fd, 0, os.SEEK_END)
            except OSError:
                size = 0
            if size <= 0:
                return
            blocks = max(1, size // BLOCK_SIZE)
            for index in range(self.seeks):
                half = index // 2
                offset = half % blocks if index % 2 == 0 else max(0, blocks - 1 - half)
                try:
                    # mmap gives preadv an aligned buffer; O_DIRECT bypasses Linux's
                    # page cache so every read becomes a physical drive command.
                    os.preadv(fd, [buffer], offset * BLOCK_SIZE)
                except OSError as error:
                    LOGGER.warning("Floppy tactile seek failed: %s", error)
                    break
            else:
                LOGGER.info("Floppy tactile feedback: %d physical seeks", self.seeks)
        finally:
            buffer.close()
            os.close(fd)


def track_identity(player: dict) -> str:
    """Return a stable identity for the current track."""
    return player.get("spotify_track_id") or (
        f"{player.get('track')}|{player.get('album')}|{player.get('artists')}"
    )


def near_track_end(
    player: dict | None,
    last_thumped: str | None,
    window_ms: int = TRACK_END_WINDOW_MS,
) -> tuple[bool, str | None]:
    """Decide whether to thump near the end of a track.

    Returns ``(should_thump, new_last_thumped)``. Thumps at most once per track
    when playback is within ``window_ms`` of the end. ``last_thumped`` is reset
    whenever we observe playback clearly away from the end (a new track or a
    loop restart), so repeated tracks thump again.
    """
    if not player or not player.get("is_playing"):
        return False, last_thumped
    duration = player.get("duration_ms") or 0
    position = player.get("progress_ms") or 0
    identity = track_identity(player)
    if duration > 0 and 0 <= duration - position <= window_ms:
        if identity != last_thumped:
            return True, identity
        return False, last_thumped
    return False, None
