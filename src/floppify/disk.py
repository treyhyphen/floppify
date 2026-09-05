"""Poll removable media for Floppify playback instructions."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from .models import DiskConfig

LOGGER = logging.getLogger(__name__)
CONFIG_NAMES = ("floppify.json", ".floppify.json")


class DiskWatcher:
    """Detect inserted mounted disks and emit validated playback configurations."""

    def __init__(
        self,
        roots: tuple[Path, ...],
        on_insert: Callable[[DiskConfig, Path], Awaitable[None]],
        poll_seconds: float = 2.0,
        on_eject: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Configure media roots and insertion/ejection callbacks."""
        self.roots = roots
        self.on_insert = on_insert
        self.on_eject = on_eject
        self.poll_seconds = poll_seconds
        self.current_path: Path | None = None
        self.current_config: DiskConfig | None = None
        self.error: str | None = None
        self._seen: set[Path] = set()
        self._stop = asyncio.Event()

    async def run(self) -> None:
        """Poll until stopped, firing once for each newly visible config file."""
        while not self._stop.is_set():
            await self.scan_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)

    async def scan_once(self) -> None:
        """Scan media roots once; exposed separately for deterministic tests."""
        found = self._find_configs()
        self._seen.intersection_update(found)
        if not found:
            ejected = self.current_path is not None
            self.current_path = None
            self.current_config = None
            self.error = None
            if ejected and self.on_eject is not None:
                try:
                    await self.on_eject()
                except Exception as exc:
                    self.error = f"Stop failed: {exc}"
                    LOGGER.warning("%s", self.error)
            return
        for path in sorted(found):
            if path in self._seen:
                continue
            self._seen.add(path)
            try:
                config = DiskConfig.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                self.current_path = path
                self.current_config = None
                self.error = f"Invalid {path.name}: {exc}"
                LOGGER.warning("%s", self.error)
                continue
            self.current_path = path
            self.current_config = config
            self.error = None
            try:
                await self.on_insert(config, path)
            except Exception as exc:
                self.error = f"Playback failed: {exc}"
                LOGGER.warning("%s", self.error)

    def stop(self) -> None:
        """Request a clean watcher shutdown."""
        self._stop.set()

    def status(self) -> dict[str, object]:
        """Return disk state suitable for the web API."""
        return {
            "inserted": self.current_path is not None,
            "path": str(self.current_path) if self.current_path else None,
            "config": self.current_config.model_dump() if self.current_config else None,
            "error": self.error,
        }

    def _find_configs(self) -> set[Path]:
        """Find configs at a root or common ``/media/user/label`` mount depth."""
        found: set[Path] = set()
        for root in self.roots:
            if not root.exists():
                continue
            for name in CONFIG_NAMES:
                candidates = (
                    root / name,
                    *root.glob(f"*/{name}"),
                    *root.glob(f"*/*/{name}"),
                )
                found.update(candidate for candidate in candidates if candidate.is_file())
        return found
