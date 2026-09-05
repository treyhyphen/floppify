"""Local Sonos discovery and playback using the SoCo library."""

import asyncio
import socket
import time
from typing import Any

import soco
from soco.exceptions import SoCoException
from soco.music_services.accounts import Account
from soco.plugins.sharelink import ShareLinkPlugin

from .base import OutputError, PlaybackOutput


class SonosOutput(PlaybackOutput):
    """Expose Sonos rooms as direct Floppify playback targets."""

    prefix = "sonos"

    def __init__(
        self,
        discovery_timeout: float = 2.0,
        cache_seconds: float = 15.0,
        interface_addr: str | None = None,
    ) -> None:
        """Configure SSDP discovery timeout and device-cache lifetime."""
        self.discovery_timeout = discovery_timeout
        self.cache_seconds = cache_seconds
        self.interface_addr = interface_addr or self._default_interface_addr()
        self._speakers: dict[str, Any] = {}
        self._last_discovery = 0.0

    async def devices(self) -> list[dict[str, Any]]:
        """Discover visible Sonos rooms without blocking the event loop."""
        await self._refresh()
        return await asyncio.to_thread(self._device_records)

    async def play_context(
        self, context_uri: str, device_id: str, shuffle: bool | None = None
    ) -> None:
        """Replace a Sonos group's queue with a Spotify album or playlist."""
        speaker = await self._speaker(device_id)
        await asyncio.to_thread(self._play_context, speaker, context_uri, shuffle)

    async def command(self, command: str, device_id: str, **kwargs: Any) -> None:
        """Execute transport, shuffle, or room-volume controls."""
        speaker = await self._speaker(device_id)
        await asyncio.to_thread(self._command, speaker, command, kwargs)

    async def _refresh(self, force: bool = False) -> None:
        """Refresh the SSDP cache when stale or explicitly requested."""
        cache_fresh = time.monotonic() - self._last_discovery < self.cache_seconds
        if not force and self._speakers and cache_fresh:
            return
        try:
            speakers = await asyncio.to_thread(
                soco.discover,
                timeout=self.discovery_timeout,
                include_invisible=False,
                interface_addr=self.interface_addr,
            )
        except Exception as exc:
            raise OutputError(f"Sonos discovery failed: {exc}") from exc
        self._speakers = {
            self._device_id(speaker): speaker
            for speaker in (speakers or set())
            if getattr(speaker, "uid", None)
        }
        self._last_discovery = time.monotonic()

    async def _speaker(self, device_id: str) -> Any:
        """Resolve a prefixed device ID, refreshing once if necessary."""
        if not self.handles(device_id):
            raise OutputError("Invalid Sonos device identifier")
        await self._refresh()
        speaker = self._speakers.get(device_id)
        if speaker is None:
            await self._refresh(force=True)
            speaker = self._speakers.get(device_id)
        if speaker is None:
            raise OutputError("The selected Sonos room is no longer available")
        return speaker

    def _device_records(self) -> list[dict[str, Any]]:
        """Convert cached SoCo speakers into Floppify device records."""
        records = []
        for device_id, speaker in self._speakers.items():
            try:
                name = speaker.player_name
                model = speaker.get_speaker_info().get("model_name") or "Sonos"
                transport = speaker.get_current_transport_info()
                active = transport.get("current_transport_state") == "PLAYING"
            except Exception:
                name = getattr(speaker, "ip_address", "Sonos")
                model = "Sonos"
                active = False
            records.append(
                {
                    "id": device_id,
                    "is_active": active,
                    "is_private_session": False,
                    "is_restricted": False,
                    "name": name,
                    "supports_volume": True,
                    "type": "Speaker",
                    "source": "sonos",
                    "description": model,
                }
            )
        return sorted(records, key=lambda item: item["name"].casefold())

    @staticmethod
    def _default_interface_addr() -> str | None:
        """Choose the IPv4 interface used to reach the SSDP multicast group."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("239.255.255.250", 1900))
                return str(probe.getsockname()[0])
        except OSError:
            return None

    @staticmethod
    def _device_id(speaker: Any) -> str:
        """Create a stable namespaced ID from a Sonos UID."""
        return f"sonos:{speaker.uid}"

    @staticmethod
    def _coordinator(speaker: Any) -> Any:
        """Return the group coordinator required for queue operations."""
        try:
            return speaker.group.coordinator
        except Exception:
            return speaker

    @classmethod
    def _play_context(cls, speaker: Any, context_uri: str, shuffle: bool | None) -> None:
        """Synchronously queue and play a Spotify share link on Sonos."""
        if context_uri.startswith("https://open.spotify.com/"):
            parts = context_uri.split("?", 1)[0].rstrip("/").split("/")
            context_uri = f"spotify:{parts[-2]}:{parts[-1]}"
        if not context_uri.startswith(("spotify:album:", "spotify:playlist:")):
            raise OutputError("Sonos supports Spotify album and playlist disks")
        coordinator = cls._coordinator(speaker)
        try:
            coordinator.stop()
            coordinator.clear_queue()
            queue_position = ShareLinkPlugin(coordinator).add_share_link_to_queue(context_uri)
            coordinator.play_mode = "SHUFFLE_NOREPEAT" if shuffle else "NORMAL"
            coordinator.play_from_queue(max(queue_position - 1, 0))
        except SoCoException as exc:
            if not cls._spotify_linked(coordinator):
                raise OutputError(
                    "Sonos isn't linked to Spotify yet — open the Sonos app and add "
                    "Spotify under Settings → Services & Voice → Add a Service, then sign in"
                ) from exc
            raise OutputError(
                "Sonos could not play this Spotify link; confirm Spotify is linked in the Sonos app"
            ) from exc

    @staticmethod
    def _spotify_linked(speaker: Any) -> bool:
        """Return whether the Sonos system has an authorized Spotify account."""
        try:
            accounts = Account.get_accounts(speaker)
        except Exception:
            return True  # Unknown; surface the upstream error instead of guessing.
        return any(
            account.service_type in {"2311", "3079"} and not account.deleted
            for account in accounts.values()
        )

    @classmethod
    def _command(cls, speaker: Any, command: str, kwargs: dict[str, Any]) -> None:
        """Synchronously execute a command through SoCo."""
        coordinator = cls._coordinator(speaker)
        try:
            if command == "transfer":
                return
            if command == "pause":
                coordinator.pause()
            elif command == "resume":
                coordinator.play()
            elif command == "next":
                coordinator.next()
            elif command == "previous":
                coordinator.previous()
            elif command == "shuffle":
                coordinator.play_mode = "SHUFFLE_NOREPEAT" if kwargs["enabled"] else "NORMAL"
            elif command == "volume":
                speaker.volume = int(kwargs["volume_percent"])
            else:
                raise OutputError(f"Unsupported Sonos command: {command}")
        except SoCoException as exc:
            raise OutputError(f"Sonos command failed: {exc}") from exc
