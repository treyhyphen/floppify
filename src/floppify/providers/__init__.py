"""Music-provider integrations."""

from .base import PlaybackProvider
from .spotify import SpotifyProvider

__all__ = ["PlaybackProvider", "SpotifyProvider"]
