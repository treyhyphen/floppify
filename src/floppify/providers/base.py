"""Playback-provider contract used by the UI and disk watcher."""

from abc import ABC, abstractmethod
from typing import Any


class PlaybackProvider(ABC):
    """Abstract interface for controllable music providers."""

    name: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Return whether provider application credentials exist."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Return whether a user authorization token exists."""

    @abstractmethod
    def authorization_url(self) -> str:
        """Create a user authorization URL."""

    @abstractmethod
    async def handle_callback(self, code: str, state: str) -> None:
        """Exchange an authorization callback for provider tokens."""

    @abstractmethod
    async def devices(self) -> list[dict[str, Any]]:
        """List available playback devices."""

    @abstractmethod
    async def state(self) -> dict[str, Any] | None:
        """Return normalized current playback state."""

    @abstractmethod
    async def play_context(
        self, context_uri: str, device_id: str | None = None, shuffle: bool | None = None
    ) -> None:
        """Begin playback of an album, artist, or playlist."""

    @abstractmethod
    async def command(self, command: str, **kwargs: Any) -> None:
        """Execute a provider-neutral playback command."""
