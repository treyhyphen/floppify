"""Spotify Web API provider using OAuth Authorization Code with PKCE."""

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from .base import PlaybackProvider

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = (
    "playlist-read-private",
    "user-read-currently-playing",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-private",
)


class SpotifyError(RuntimeError):
    """A normalized Spotify API or authorization error."""


class SpotifyProvider(PlaybackProvider):
    """Control Spotify playback without storing a client secret."""

    name = "spotify"

    def __init__(self, client_id: str, redirect_uri: str, token_path: Path) -> None:
        """Initialize Spotify with a public client ID and token file."""
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.token_path = token_path
        self._pending: dict[str, tuple[str, float]] = {}
        self._token: dict[str, Any] | None = self._load_token()

    @property
    def configured(self) -> bool:
        """Return whether a Spotify client ID has been configured."""
        return bool(self.client_id)

    @property
    def connected(self) -> bool:
        """Return whether authorization tokens are available."""
        return bool(self._token and self._token.get("refresh_token"))

    def authorization_url(self) -> str:
        """Create a Spotify PKCE authorization URL and remember its verifier."""
        if not self.configured:
            raise SpotifyError("Spotify client ID is not configured")
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        self._pending[state] = (verifier, time.time())
        self._pending = {
            key: value for key, value in self._pending.items() if time.time() - value[1] < 600
        }
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": " ".join(SCOPES),
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "show_dialog": "true",
            }
        )
        return f"{AUTH_URL}?{query}"

    async def handle_callback(self, code: str, state: str) -> None:
        """Validate OAuth state and exchange an authorization code for tokens."""
        pending = self._pending.pop(state, None)
        if not pending or time.time() - pending[1] >= 600:
            raise SpotifyError("Spotify authorization state is missing or expired")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "code_verifier": pending[0],
                },
            )
        self._token = self._token_response(response)
        self._save_token()

    async def devices(self) -> list[dict[str, Any]]:
        """Return Spotify Connect devices."""
        payload = await self._request("GET", "/me/player/devices")
        return payload.get("devices", [])

    async def state(self) -> dict[str, Any] | None:
        """Return a compact, UI-friendly playback state."""
        payload = await self._request("GET", "/me/player", allow_empty=True)
        if not payload:
            return None
        item = payload.get("item") or {}
        album = item.get("album") or {}
        images = album.get("images") or []
        context = payload.get("context") or {}
        return {
            "is_playing": bool(payload.get("is_playing")),
            "shuffle": bool(payload.get("shuffle_state")),
            "progress_ms": payload.get("progress_ms") or 0,
            "duration_ms": item.get("duration_ms") or 0,
            "track": item.get("name"),
            "artists": ", ".join(artist.get("name", "") for artist in item.get("artists", [])),
            "album": album.get("name"),
            "artwork": images[0].get("url") if images else None,
            "context_uri": context.get("uri"),
            "device": payload.get("device"),
        }

    async def track_artwork(self, track_id: str) -> str | None:
        """Resolve a Spotify track's album artwork URL."""
        payload = await self._request("GET", f"/tracks/{track_id}")
        images = (payload.get("album") or {}).get("images") or []
        return images[0].get("url") if images else None

    async def play_context(
        self, context_uri: str, device_id: str | None = None, shuffle: bool | None = None
    ) -> None:
        """Start a Spotify album, artist, or playlist context."""
        uri = self._normalize_context_uri(context_uri)
        if shuffle is not None:
            await self.command("shuffle", device_id=device_id, enabled=shuffle)
        await self._request(
            "PUT",
            "/me/player/play",
            device_id=device_id,
            expect_json=False,
            json={"context_uri": uri},
        )

    async def command(self, command: str, **kwargs: Any) -> None:
        """Run a playback command using Spotify's player endpoints."""
        device_id = kwargs.get("device_id")
        routes: dict[str, tuple[str, str]] = {
            "pause": ("PUT", "/me/player/pause"),
            "resume": ("PUT", "/me/player/play"),
            "next": ("POST", "/me/player/next"),
            "previous": ("POST", "/me/player/previous"),
        }
        if command in routes:
            method, path = routes[command]
            await self._request(method, path, device_id=device_id, expect_json=False)
            return
        if command == "volume":
            await self._request(
                "PUT", "/me/player/volume", device_id=device_id,
                expect_json=False,
                params={"volume_percent": int(kwargs["volume_percent"])},
            )
            return
        if command == "shuffle":
            await self._request(
                "PUT", "/me/player/shuffle", device_id=device_id,
                expect_json=False,
                params={"state": str(bool(kwargs["enabled"])).lower()},
            )
            return
        if command == "transfer":
            await self._request(
                "PUT",
                "/me/player",
                expect_json=False,
                json={"device_ids": [kwargs["device_id"]], "play": False},
            )
            return
        raise SpotifyError(f"Unsupported Spotify command: {command}")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        device_id: str | None = None,
        allow_empty: bool = False,
        expect_json: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send an authenticated API request, refreshing the token when needed."""
        token = await self._access_token()
        params = dict(kwargs.pop("params", {}))
        if device_id:
            params["device_id"] = device_id
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(
                method, f"{API_URL}{path}", headers={"Authorization": f"Bearer {token}"},
                params=params, **kwargs,
            )
            if response.status_code == 401:
                token = await self._refresh()
                response = await client.request(
                    method, f"{API_URL}{path}", headers={"Authorization": f"Bearer {token}"},
                    params=params, **kwargs,
                )
        if response.status_code == 204 and allow_empty:
            return {}
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {})
                message = detail.get("message") if isinstance(detail, dict) else str(detail)
            except (ValueError, AttributeError):
                message = response.text
            message = message or "request failed"
            if "no active device" in message.lower():
                message = "No active Spotify device; open Spotify on a device, then refresh devices"
            elif "restriction violated" in message.lower():
                message = (
                    "This control is unavailable for the current Spotify device "
                    "or playback state"
                )
            raise SpotifyError(f"Spotify API {response.status_code}: {message}")
        if not expect_json or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise SpotifyError("Spotify returned an invalid response; try again") from exc

    async def _access_token(self) -> str:
        """Return a valid access token, refreshing shortly before expiry."""
        if not self._token:
            raise SpotifyError("Spotify is not connected")
        if float(self._token.get("expires_at", 0)) <= time.time() + 30:
            return await self._refresh()
        return str(self._token["access_token"])

    async def _refresh(self) -> str:
        """Refresh and persist the current Spotify access token."""
        if not self._token or not self._token.get("refresh_token"):
            raise SpotifyError("Spotify authorization has expired; reconnect the account")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": self._token["refresh_token"],
                },
            )
        refreshed = self._token_response(response)
        refreshed.setdefault("refresh_token", self._token["refresh_token"])
        self._token = refreshed
        self._save_token()
        return str(refreshed["access_token"])

    @staticmethod
    def _token_response(response: httpx.Response) -> dict[str, Any]:
        """Validate and normalize a Spotify token response."""
        if response.status_code >= 400:
            try:
                message = response.json().get("error_description") or response.json().get("error")
            except ValueError:
                message = response.text
            raise SpotifyError(f"Spotify authorization failed: {message}")
        token = response.json()
        token["expires_at"] = time.time() + int(token.get("expires_in", 3600))
        return token

    def _load_token(self) -> dict[str, Any] | None:
        """Load a previously authorized token without exposing it to logs."""
        try:
            return json.loads(self.token_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            return None

    def _save_token(self) -> None:
        """Atomically persist tokens with owner-only permissions."""
        if not self._token:
            return
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.token_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._token))
        os.chmod(temporary, 0o600)
        temporary.replace(self.token_path)

    @staticmethod
    def _normalize_context_uri(value: str) -> str:
        """Convert an open.spotify.com context URL to a Spotify URI."""
        if value.startswith("spotify:"):
            return value
        parsed = urlparse(value)
        parts = parsed.path.strip("/").split("/")
        if parsed.netloc != "open.spotify.com" or len(parts) < 2:
            raise SpotifyError("Invalid Spotify context URI")
        kind, identifier = parts[-2], parts[-1]
        if kind not in {"album", "playlist", "artist"}:
            raise SpotifyError("Disk must reference a Spotify album, playlist, or artist")
        return f"spotify:{kind}:{identifier}"
