"""FastAPI application and provider-neutral playback API."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings
from .disk import DiskWatcher
from .models import DeviceRequest, PlayRequest, ShuffleRequest, VolumeRequest
from .providers import PlaybackProvider, SpotifyProvider

LOGGER = logging.getLogger(__name__)
PACKAGE_DIR = Path(__file__).parent


def create_app(
    settings: Settings | None = None, provider: PlaybackProvider | None = None
) -> FastAPI:
    """Create the Floppify web application with injectable dependencies."""
    config = settings or Settings()
    playback = provider or SpotifyProvider(
        config.spotify_client_id, config.spotify_redirect_uri, config.token_path
    )

    async def play_disk(disk_config: Any, path: Path) -> None:
        """Start playback when the disk watcher emits a valid instruction."""
        if disk_config.provider != playback.name:
            raise RuntimeError(f"Provider {disk_config.provider!r} is not installed")
        LOGGER.info("Playing %s from %s", disk_config.uri, path)
        await playback.play_context(disk_config.uri, shuffle=disk_config.shuffle)

    watcher = DiskWatcher(config.media_root_paths, play_disk, config.disk_poll_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        config.state_dir.mkdir(parents=True, exist_ok=True)
        task = asyncio.create_task(watcher.run(), name="floppy-disk-watcher")
        yield
        watcher.stop()
        await task

    app = FastAPI(title="Floppify", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.provider = playback
    app.state.disk_watcher = watcher
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

    def provider_error(exc: Exception) -> HTTPException:
        """Map provider failures to an actionable API response."""
        message = str(exc)
        status = 401 if "not connected" in message.lower() else 502
        return HTTPException(status_code=status, detail=message)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """Render the touch-first kiosk interface."""
        return templates.TemplateResponse(request, "index.html", {"provider": playback.name})

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Report process health without contacting Spotify."""
        return {"status": "ok", "provider": playback.name}

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        """Return provider, disk, and current playback status."""
        player = None
        error = None
        if playback.connected:
            try:
                player = await playback.state()
            except Exception as exc:  # keep kiosk useful during provider outages
                error = str(exc)
        return {
            "provider": {
                "name": playback.name,
                "configured": playback.configured,
                "connected": playback.connected,
            },
            "disk": watcher.status(),
            "player": player,
            "error": error,
        }

    @app.get("/api/devices")
    async def devices() -> dict[str, Any]:
        """List playback targets from the active provider."""
        try:
            return {"devices": await playback.devices()}
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.get("/auth/spotify/login")
    async def spotify_login() -> RedirectResponse:
        """Redirect the kiosk browser to Spotify authorization."""
        try:
            return RedirectResponse(playback.authorization_url())
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.get("/auth/spotify/callback")
    async def spotify_callback(
        code: Annotated[str | None, Query()] = None,
        state: Annotated[str | None, Query()] = None,
        error: Annotated[str | None, Query()] = None,
    ) -> RedirectResponse:
        """Complete Spotify authorization and return to the kiosk."""
        if error:
            return RedirectResponse(f"/?auth_error={error}")
        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing Spotify callback parameters")
        try:
            await playback.handle_callback(code, state)
        except Exception as exc:
            raise provider_error(exc) from exc
        return RedirectResponse("/?connected=1")

    @app.post("/api/play", status_code=204)
    async def play(request: PlayRequest) -> None:
        """Play the current disk context or resume current playback."""
        try:
            context_uri = request.context_uri
            if not context_uri and watcher.current_config:
                context_uri = watcher.current_config.uri
            if context_uri:
                shuffle = request.shuffle
                if shuffle is None and watcher.current_config:
                    shuffle = watcher.current_config.shuffle
                await playback.play_context(context_uri, request.device_id, shuffle)
            else:
                await playback.command("resume", device_id=request.device_id)
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/pause", status_code=204)
    async def pause(request: DeviceRequest) -> None:
        """Pause playback."""
        try:
            await playback.command("pause", device_id=request.device_id)
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/next", status_code=204)
    async def next_track(request: DeviceRequest) -> None:
        """Skip to the next track."""
        try:
            await playback.command("next", device_id=request.device_id)
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/previous", status_code=204)
    async def previous_track(request: DeviceRequest) -> None:
        """Return to the previous track."""
        try:
            await playback.command("previous", device_id=request.device_id)
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/shuffle", status_code=204)
    async def shuffle(request: ShuffleRequest) -> None:
        """Set provider shuffle mode."""
        try:
            await playback.command(
                "shuffle", device_id=request.device_id, enabled=request.enabled
            )
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/volume", status_code=204)
    async def volume(request: VolumeRequest) -> None:
        """Set the active playback device volume."""
        try:
            await playback.command(
                "volume", device_id=request.device_id, volume_percent=request.volume_percent
            )
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/transfer", status_code=204)
    async def transfer(request: DeviceRequest) -> None:
        """Transfer playback to a selected device."""
        if not request.device_id:
            raise HTTPException(status_code=422, detail="device_id is required")
        try:
            await playback.command("transfer", device_id=request.device_id)
        except Exception as exc:
            raise provider_error(exc) from exc

    return app


app = create_app()


def run() -> None:
    """Run Floppify using its configured bind address."""
    settings = Settings()
    uvicorn.run("floppify.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
