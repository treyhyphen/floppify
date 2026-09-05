"""Provider-neutral request and disk configuration models."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class DiskConfig(BaseModel):
    """A playback instruction stored on a floppy disk."""

    version: int = 1
    provider: str = "spotify"
    type: Literal["album", "playlist", "artist"]
    uri: str
    shuffle: bool = False
    name: str | None = None

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        """Reject values that are not Spotify context URIs or URLs."""
        if not (value.startswith("spotify:") or value.startswith("https://open.spotify.com/")):
            raise ValueError("uri must be a Spotify URI or open.spotify.com URL")
        return value


class DeviceRequest(BaseModel):
    """Request targeting an optional playback device."""

    device_id: str | None = None


class PlayRequest(DeviceRequest):
    """Request to begin a provider context."""

    context_uri: str | None = None
    shuffle: bool | None = None


class VolumeRequest(DeviceRequest):
    """Request to set playback volume."""

    volume_percent: int = Field(ge=0, le=100)


class ShuffleRequest(DeviceRequest):
    """Request to change shuffle state."""

    enabled: bool
