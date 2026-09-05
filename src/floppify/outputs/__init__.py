"""Local playback-output integrations."""

from .base import OutputError, PlaybackOutput
from .sonos import SonosOutput

__all__ = ["OutputError", "PlaybackOutput", "SonosOutput"]
