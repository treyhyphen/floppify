"""Tests for Spotify URI and OAuth helper behavior."""

import time
from pathlib import Path

import httpx
import pytest

from floppify.providers.spotify import SpotifyError, SpotifyProvider


def test_normalizes_open_spotify_context_url() -> None:
    """Shared Spotify URLs should become Web API context URIs."""
    assert (
        SpotifyProvider._normalize_context_uri("https://open.spotify.com/album/abc?si=123")
        == "spotify:album:abc"
    )


def test_rejects_track_as_context() -> None:
    """A single track cannot be sent as a context URI."""
    with pytest.raises(SpotifyError, match="album, playlist, or artist"):
        SpotifyProvider._normalize_context_uri("https://open.spotify.com/track/abc")


def test_authorization_url_uses_pkce(tmp_path: Path) -> None:
    """OAuth must not require or expose a Spotify client secret."""
    provider = SpotifyProvider("client-id", "http://127.0.0.1/callback", tmp_path / "token.json")
    url = provider.authorization_url()
    assert "code_challenge_method=S256" in url
    assert "client_secret" not in url


@pytest.mark.asyncio
async def test_player_command_accepts_non_json_success(tmp_path: Path, monkeypatch) -> None:
    """Spotify write endpoints may return a non-JSON success body."""
    provider = SpotifyProvider("client-id", "http://localhost/callback", tmp_path / "token")
    provider._token = {
        "access_token": "test-token",
        "refresh_token": "test-refresh",
        "expires_at": time.time() + 3600,
    }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, *args, **kwargs):
            request = httpx.Request("POST", "https://api.spotify.test/player/next")
            return httpx.Response(200, content=b"not-json", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    await provider.command("next")


@pytest.mark.asyncio
async def test_restriction_error_is_actionable(tmp_path: Path, monkeypatch) -> None:
    """Opaque Spotify restriction errors should become useful UI text."""
    provider = SpotifyProvider("client-id", "http://localhost/callback", tmp_path / "token")
    provider._token = {
        "access_token": "test-token",
        "refresh_token": "test-refresh",
        "expires_at": time.time() + 3600,
    }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, *args, **kwargs):
            request = httpx.Request("PUT", "https://api.spotify.test/player/pause")
            return httpx.Response(
                403,
                json={"error": {"message": "Restriction violated"}},
                request=request,
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    with pytest.raises(SpotifyError, match="unavailable for the current Spotify device"):
        await provider.command("pause")
