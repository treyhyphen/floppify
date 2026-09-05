"""Provider-neutral local playback-output contract."""

from abc import ABC, abstractmethod
from typing import Any


class OutputError(RuntimeError):
    """A normalized local playback-output error."""


class PlaybackOutput(ABC):
    """Discover and control local playback hardware."""

    prefix: str

    def handles(self, device_id: str | None) -> bool:
        """Return whether this adapter owns a device identifier."""
        return bool(device_id and device_id.startswith(f"{self.prefix}:"))

    @abstractmethod
    async def devices(self) -> list[dict[str, Any]]:
        """List local devices in the provider-neutral device shape."""

    @abstractmethod
    async def play_context(
        self, context_uri: str, device_id: str, shuffle: bool | None = None
    ) -> None:
        """Replace the target queue and begin a provider context."""

    @abstractmethod
    async def command(self, command: str, device_id: str, **kwargs: Any) -> None:
        """Run a provider-neutral command against a local device."""

    @abstractmethod
    async def state(self, device_id: str) -> dict[str, Any]:
        """Return the current playback state for a local device."""
