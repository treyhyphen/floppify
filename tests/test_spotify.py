"""Tests for Spotify URI and OAuth helper behavior."""

from pathlib import Path

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
