"""Tests for the web UI and provider-neutral playback endpoints."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from floppify.config import Settings
from floppify.main import create_app
from floppify.providers.base import PlaybackProvider


class FakeProvider(PlaybackProvider):
    """Record API operations without contacting a music service."""

    name = "spotify"

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

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
        return {"is_playing": True, "track": "Test Track", "duration_ms": 1000}

    async def play_context(
        self, context_uri: str, device_id: str | None = None, shuffle: bool | None = None
    ) -> None:
        self.calls.append(("play", context_uri, device_id, shuffle))

    async def command(self, command: str, **kwargs: Any) -> None:
        self.calls.append((command, kwargs))


def test_health_status_and_index(tmp_path: Path) -> None:
    """The kiosk and read-only API should render with provider state."""
    provider = FakeProvider()
    app = create_app(Settings(state_dir=tmp_path, media_roots=str(tmp_path)), provider)
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok", "provider": "spotify"}
        status = client.get("/api/status").json()
        assert status["provider"]["connected"] is True
        assert status["player"]["track"] == "Test Track"
        page = client.get("/")
        assert page.status_code == 200
        assert "FLOPPIFY" in page.text
        assert "viewport-fit=cover" in page.text
        assert "styles.css?v=mobile-footer-1" in page.text
        css = client.get("/static/styles.css")
        assert css.status_code == 200
        assert "height: 100dvh" in css.text
        assert "safe-area-inset-bottom" in css.text


def test_playback_commands_are_provider_neutral(tmp_path: Path) -> None:
    """Touch controls should delegate through the provider contract."""
    provider = FakeProvider()
    app = create_app(Settings(state_dir=tmp_path, media_roots=str(tmp_path)), provider)
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
    app = create_app(Settings(state_dir=tmp_path, media_roots=str(tmp_path)), FakeProvider())
    with TestClient(app) as client:
        assert client.post("/api/transfer", json={}).status_code == 422
