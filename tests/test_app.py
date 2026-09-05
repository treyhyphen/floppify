"""Tests for the web UI and provider-neutral playback endpoints."""

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from floppify.config import Settings
from floppify.main import create_app
from floppify.outputs import PlaybackOutput
from floppify.providers.base import PlaybackProvider


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Build test settings with floppy thumping disabled by default."""
    return Settings(
        state_dir=tmp_path,
        media_roots=str(tmp_path),
        floppy_thump_enabled=False,
        **overrides,
    )


class FakeProvider(PlaybackProvider):
    """Record API operations without contacting a music service."""

    name = "spotify"

    def __init__(
        self,
        context_uri: str | None = "spotify:playlist:abc",
        state_override: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.context_uri = context_uri
        self.state_override = state_override

    @property
    def configured(self) -> bool:
        return True

    @property
    def connected(self) -> bool:
        return True

    def authorization_url(self) -> str:
        return "https://accounts.spotify.test/authorize"

    async def handle_callback(self, code: str, state: str) -> None:
        self.calls.append(("callback", code, state))

    async def devices(self) -> list[dict[str, Any]]:
        return [{"id": "pi", "name": "Floppify", "is_active": True}]

    async def state(self) -> dict[str, Any]:
        if self.state_override is not None:
            return self.state_override
        return {
            "is_playing": True,
            "track": "Test Track",
            "duration_ms": 1000,
            "context_uri": self.context_uri,
        }

    async def play_context(
        self, context_uri: str, device_id: str | None = None, shuffle: bool | None = None
    ) -> None:
        self.calls.append(("play", context_uri, device_id, shuffle))

    async def command(self, command: str, **kwargs: Any) -> None:
        self.calls.append((command, kwargs))

    async def track_artwork(self, track_id: str) -> str | None:
        self.calls.append(("track_artwork", track_id))
        return f"https://example.test/art/{track_id}.jpg"


class FakeOutput(PlaybackOutput):
    """Record local-output routing without contacting hardware."""

    prefix = "sonos"

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def devices(self) -> list[dict[str, Any]]:
        return [{"id": "sonos:room", "name": "Living Room", "source": "sonos"}]

    async def play_context(
        self, context_uri: str, device_id: str, shuffle: bool | None = None
    ) -> None:
        self.calls.append(("play", context_uri, device_id, shuffle))

    async def command(self, command: str, device_id: str, **kwargs: Any) -> None:
        self.calls.append((command, device_id, kwargs))

    async def state(self, device_id: str) -> dict[str, Any]:
        self.calls.append(("state", device_id))
        return {
            "is_playing": True,
            "shuffle": False,
            "progress_ms": 30000,
            "duration_ms": 180000,
            "track": "Sonos Track",
            "artists": "Sonos Artist",
            "album": "Sonos Album",
            "artwork": None,
            "spotify_track_id": "sonos-track-1",
            "context_uri": None,
            "device": {"id": device_id, "name": "Living Room", "volume_percent": 42},
        }

    async def stop(self, device_id: str) -> None:
        self.calls.append(("stop", device_id))


class FakeThumper:
    """Record floppy thumps without touching hardware."""

    def __init__(self) -> None:
        self.thumps = 0
        self.seek_counts: list[int] = []

    async def thump(self, seeks: int = 6) -> None:
        self.thumps += 1
        self.seek_counts.append(seeks)


def wait_for_thumps(thumper: FakeThumper, expected: int) -> None:
    """Wait briefly for an asynchronously scheduled test thump."""
    deadline = time.time() + 1.0
    while thumper.thumps < expected and time.time() < deadline:
        time.sleep(0.01)
    assert thumper.thumps == expected


def test_health_status_and_index(tmp_path: Path) -> None:
    """The kiosk and read-only API should render with provider state."""
    provider = FakeProvider()
    app = create_app(make_settings(tmp_path), provider)
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok", "provider": "spotify"}
        status = client.get("/api/status").json()
        assert status["provider"]["connected"] is True
        assert status["player"]["track"] == "Test Track"
        page = client.get("/")
        assert page.status_code == 200
        assert "FLOPPIFY" in page.text
        assert "viewport-fit=cover" in page.text
        assert "skins/base.css?v=skins-2" in page.text
        assert "skins/spotify.css?v=skin-2" in page.text
        assert "skins/registry.js?v=skins-3" in page.text
        assert "app.js?v=skins-2" in page.text
        assert 'id="skin"' in page.text
        assert 'class="taskbar"' in page.text
        assert "control-button" in page.text
        assert 'class="winamp-lcd"' in page.text
        base_css = client.get("/static/skins/base.css")
        spotify_css = client.get("/static/skins/spotify.css")
        winamp_css = client.get("/static/skins/winamp98.css")
        registry = client.get("/static/skins/registry.js")
        assets = (base_css, spotify_css, winamp_css, registry)
        assert all(asset.status_code == 200 for asset in assets)
        assert "height: 100dvh" in spotify_css.text
        assert "safe-area-inset-bottom" in spotify_css.text
        assert "Windows" not in spotify_css.text
        assert ".taskbar" in winamp_css.text
        assert "inset: 0 0 34px" in winamp_css.text
        assert ".winamp-analyzer" in winamp_css.text
        assert 'id: "winamp98"' in registry.text
        assert ".control-button--primary" in spotify_css.text


def test_playback_commands_are_provider_neutral(tmp_path: Path) -> None:
    """Touch controls should delegate through the provider contract."""
    provider = FakeProvider()
    app = create_app(make_settings(tmp_path), provider)
    with TestClient(app) as client:
        response = client.post(
            "/api/play",
            json={"context_uri": "spotify:album:abc", "device_id": "pi", "shuffle": False},
        )
        assert response.status_code == 204
        assert provider.calls[-1] == ("play", "spotify:album:abc", "pi", False)

        assert client.post("/api/volume", json={"volume_percent": 72}).status_code == 204
        assert provider.calls[-1] == ("volume", {"device_id": None, "volume_percent": 72})

        assert client.post("/api/next", json={"device_id": "pi"}).status_code == 204
        assert provider.calls[-1] == ("next", {"device_id": "pi"})


def test_transfer_requires_device(tmp_path: Path) -> None:
    """A transfer request without a target should fail clearly."""
    app = create_app(make_settings(tmp_path), FakeProvider())
    with TestClient(app) as client:
        assert client.post("/api/transfer", json={}).status_code == 422


def test_transfer_to_spotify_device(tmp_path: Path) -> None:
    """Selecting a Spotify Connect device performs a normal Spotify transfer."""
    provider = FakeProvider()
    app = create_app(make_settings(tmp_path), provider)
    with TestClient(app) as client:
        response = client.post("/api/transfer", json={"device_id": "pi"})
        assert response.status_code == 200
        assert response.json()["message"] == "Transferred playback"
        assert provider.calls[-1] == ("transfer", {"device_id": "pi"})


def test_sonos_device_selection_routes_and_persists(tmp_path: Path) -> None:
    """A selected Sonos room should receive controls and future disk playback."""
    provider = FakeProvider()
    output = FakeOutput()
    settings = make_settings(tmp_path)
    app = create_app(settings, provider, outputs=[output])

    with TestClient(app) as client:
        devices = client.get("/api/devices").json()["devices"]
        assert {device["id"] for device in devices} == {"pi", "sonos:room"}

        response = client.post("/api/transfer", json={"device_id": "sonos:room"})
        assert response.status_code == 200
        assert response.json()["message"] == "Now playing on the selected speaker"
        assert settings.selected_device_path.read_text() == "sonos:room"
        assert ("pause", {}) in provider.calls
        assert output.calls[-1] == ("play", "spotify:playlist:abc", "sonos:room", None)

        response = client.post(
            "/api/play",
            json={"context_uri": "spotify:playlist:abc", "shuffle": True},
        )
        assert response.status_code == 204
        assert output.calls[-1] == (
            "play",
            "spotify:playlist:abc",
            "sonos:room",
            True,
        )
        assert client.get("/api/status").json()["selected_device_id"] == "sonos:room"


def test_sonos_transfer_without_context_errors(tmp_path: Path) -> None:
    """Selecting Sonos with nothing to play surfaces an actionable error."""
    provider = FakeProvider(context_uri=None)
    output = FakeOutput()
    app = create_app(
        make_settings(tmp_path), provider, outputs=[output]
    )
    with TestClient(app) as client:
        response = client.post("/api/transfer", json={"device_id": "sonos:room"})
        assert response.status_code == 409
        assert "insert a floppy" in response.json()["detail"].lower()


def test_status_reflects_selected_sonos_room(tmp_path: Path) -> None:
    """The now-playing panel should read from Sonos when a room is selected."""
    provider = FakeProvider()
    output = FakeOutput()
    settings = make_settings(tmp_path)
    app = create_app(settings, provider, outputs=[output])

    with TestClient(app) as client:
        client.post("/api/transfer", json={"device_id": "sonos:room"})
        status = client.get("/api/status").json()
        assert status["selected_device_id"] == "sonos:room"
        assert status["player"]["track"] == "Sonos Track"
        assert status["player"]["progress_ms"] == 30000
        assert status["player"]["artwork"] == "https://example.test/art/sonos-track-1.jpg"
        assert ("state", "sonos:room") in output.calls
        assert ("track_artwork", "sonos-track-1") in provider.calls


def test_eject_stops_local_output(tmp_path: Path) -> None:
    """Ejecting a disk should stop playback and clear the local queue."""
    provider = FakeProvider()
    output = FakeOutput()
    settings = make_settings(tmp_path, disk_poll_seconds=3600)
    app = create_app(settings, provider, outputs=[output])

    with TestClient(app) as client:
        watcher = app.state.disk_watcher
        client.post("/api/transfer", json={"device_id": "sonos:room"})

        disk = tmp_path / "MIXTAPE"
        disk.mkdir()
        config_path = disk / "floppify.json"
        config_path.write_text(
            '{"provider":"spotify","type":"playlist","uri":"spotify:playlist:abc"}'
        )
        asyncio.run(watcher.scan_once())
        assert ("play", "spotify:playlist:abc", "sonos:room", None) in output.calls

        config_path.unlink()
        asyncio.run(watcher.scan_once())
        assert ("stop", "sonos:room") in output.calls


def test_eject_endpoint_stops_selected_output(tmp_path: Path) -> None:
    """POST /api/eject should stop the selected local output immediately."""
    provider = FakeProvider()
    output = FakeOutput()
    settings = make_settings(tmp_path)
    app = create_app(settings, provider, outputs=[output])

    with TestClient(app) as client:
        client.post("/api/transfer", json={"device_id": "sonos:room"})
        response = client.post("/api/eject")
        assert response.status_code == 204
        assert ("stop", "sonos:room") in output.calls


def test_eject_endpoint_pauses_spotify_without_local_output(tmp_path: Path) -> None:
    """POST /api/eject pauses Spotify when no local output is selected."""
    provider = FakeProvider()
    app = create_app(make_settings(tmp_path), provider)

    with TestClient(app) as client:
        response = client.post("/api/eject")
        assert response.status_code == 204
        assert ("pause", {}) in provider.calls


def test_transport_controls_trigger_floppy_thump(tmp_path: Path) -> None:
    """Play/pause/next/previous should fire a floppy seek for tactile feedback."""
    provider = FakeProvider(state_override={"is_playing": False})
    thumper = FakeThumper()
    app = create_app(
        Settings(state_dir=tmp_path, media_roots=str(tmp_path)),
        provider,
        thumper=thumper,
    )

    with TestClient(app) as client:
        client.post("/api/play", json={"context_uri": "spotify:album:abc"})
        wait_for_thumps(thumper, 1)

        client.post("/api/pause", json={})
        wait_for_thumps(thumper, 2)

        client.post("/api/next", json={})
        wait_for_thumps(thumper, 3)

        client.post("/api/previous", json={})
        wait_for_thumps(thumper, 4)
        assert thumper.seek_counts == [2, 2, 6, 6]

        # Volume and shuffle are sliders/toggles, not discrete presses.
        client.post("/api/volume", json={"volume_percent": 50})
        client.post("/api/shuffle", json={"enabled": True})
        assert thumper.thumps == 4


def test_track_end_watcher_thumps_once_per_track(tmp_path: Path) -> None:
    """The background watcher thumps once as a track nears its end."""
    provider = FakeProvider(
        state_override={
            "is_playing": True,
            "duration_ms": 100000,
            "progress_ms": 99500,
            "track": "T",
            "album": "A",
            "artists": "B",
        }
    )
    thumper = FakeThumper()
    app = create_app(
        Settings(state_dir=tmp_path, media_roots=str(tmp_path)),
        provider,
        thumper=thumper,
    )

    with TestClient(app):
        deadline = time.time() + 2.0
        while thumper.thumps == 0 and time.time() < deadline:
            time.sleep(0.05)
        assert thumper.thumps == 1
        assert thumper.seek_counts == [6]

        # Same track still near the end: no repeat thump.
        time.sleep(0.8)
        assert thumper.thumps == 1
