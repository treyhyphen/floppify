"""Tests for direct Sonos discovery and playback."""

from types import SimpleNamespace

import pytest

from floppify.outputs.base import OutputError
from floppify.outputs.sonos import SonosOutput


class FakeSpeaker:
    """Minimal synchronous Sonos speaker used by adapter tests."""

    uid = "RINCON_TEST"
    player_name = "Living Room"
    ip_address = "192.0.2.10"

    def __init__(self) -> None:
        self.calls: list[object] = []
        self.volume = 20
        self.play_mode = "NORMAL"
        self.group = SimpleNamespace(coordinator=self)

    def get_speaker_info(self):
        return {"model_name": "Sonos Playbar"}

    def get_current_transport_info(self):
        return {"current_transport_state": "PLAYING"}

    def stop(self):
        self.calls.append("stop")

    def clear_queue(self):
        self.calls.append("clear")

    def play_from_queue(self, index):
        self.calls.append(("play_from_queue", index))

    def pause(self):
        self.calls.append("pause")

    def play(self):
        self.calls.append("play")

    def next(self):
        self.calls.append("next")

    def previous(self):
        self.calls.append("previous")


@pytest.mark.asyncio
async def test_discovers_sonos_device(monkeypatch) -> None:
    """SSDP rooms should become namespaced selectable devices."""
    speaker = FakeSpeaker()
    monkeypatch.setattr("floppify.outputs.sonos.soco.discover", lambda **kwargs: {speaker})
    output = SonosOutput()

    assert await output.devices() == [
        {
            "id": "sonos:RINCON_TEST",
            "is_active": True,
            "is_private_session": False,
            "is_restricted": False,
            "name": "Living Room",
            "supports_volume": True,
            "type": "Speaker",
            "source": "sonos",
            "description": "Sonos Playbar",
        }
    ]


def test_queues_spotify_playlist_on_sonos(monkeypatch) -> None:
    """Playlist playback should replace the coordinator queue and start it."""
    speaker = FakeSpeaker()

    class FakeShareLink:
        def __init__(self, coordinator):
            assert coordinator is speaker

        def add_share_link_to_queue(self, uri):
            speaker.calls.append(("queue", uri))
            return 1

    monkeypatch.setattr("floppify.outputs.sonos.ShareLinkPlugin", FakeShareLink)
    SonosOutput._play_context(speaker, "spotify:playlist:abc", True)

    assert speaker.calls == [
        "stop",
        "clear",
        ("queue", "spotify:playlist:abc"),
        ("play_from_queue", 0),
    ]
    assert speaker.play_mode == "SHUFFLE_NOREPEAT"


def test_rejects_unsupported_sonos_artist_context() -> None:
    """SoCo share links do not support Spotify artist contexts."""
    with pytest.raises(OutputError, match="album and playlist"):
        SonosOutput._play_context(FakeSpeaker(), "spotify:artist:abc", False)
