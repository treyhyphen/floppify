"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the Floppify service."""

    model_config = SettingsConfigDict(
        env_prefix="FLOPPIFY_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    host: str = "0.0.0.0"
    port: int = 8000
    spotify_client_id: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:8000/auth/spotify/callback"
    state_dir: Path = Path("/var/lib/floppify")
    media_roots: str = "/media,/mnt/floppify"
    disk_poll_seconds: float = 2.0
    kiosk_url: str = "http://127.0.0.1:8000"
    sonos_enabled: bool = True
    sonos_discovery_timeout: float = 2.0
    sonos_interface_addr: str | None = None

    @property
    def token_path(self) -> Path:
        """Return the Spotify token file path."""
        return self.state_dir / "spotify-token.json"

    @property
    def selected_device_path(self) -> Path:
        """Return the persistent selected-output file path."""
        return self.state_dir / "selected-device"

    @property
    def media_root_paths(self) -> tuple[Path, ...]:
        """Return configured removable-media roots."""
        return tuple(Path(item.strip()) for item in self.media_roots.split(",") if item.strip())
