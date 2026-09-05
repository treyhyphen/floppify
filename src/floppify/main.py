"""FastAPI application and provider-neutral playback API."""

import asyncio
import logging
import os
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
from .outputs import OutputError, PlaybackOutput, SonosOutput
from .providers import PlaybackProvider, SpotifyProvider

LOGGER = logging.getLogger(__name__)
PACKAGE_DIR = Path(__file__).parent


def create_app(
    settings: Settings | None = None,
    provider: PlaybackProvider | None = None,
    outputs: list[PlaybackOutput] | None = None,
) -> FastAPI:
    """Create the Floppify web application with injectable dependencies."""
    config = settings or Settings()
    playback = provider or SpotifyProvider(
        config.spotify_client_id, config.spotify_redirect_uri, config.token_path
    )
    local_outputs = outputs
    if local_outputs is None:
        local_outputs = (
            [
                SonosOutput(
                    discovery_timeout=config.sonos_discovery_timeout,
                    interface_addr=config.sonos_interface_addr,
                )
            ]
            if config.sonos_enabled
            else []
        )
    try:
        selected_device_id = config.selected_device_path.read_text().strip() or None
    except (FileNotFoundError, PermissionError):
        selected_device_id = None

    def output_for(device_id: str | None) -> PlaybackOutput | None:
        """Return the local-output adapter owning a device identifier."""
        return next((output for output in local_outputs if output.handles(device_id)), None)

    async def play_target(
        context_uri: str, device_id: str | None, shuffle: bool | None
    ) -> None:
        """Route playback to Spotify Connect or a local output adapter."""
        output = output_for(device_id)
        if output and device_id:
            await output.play_context(context_uri, device_id, shuffle)
        else:
            await playback.play_context(context_uri, device_id, shuffle)

    async def command_target(command: str, device_id: str | None, **kwargs: Any) -> None:
        """Route a control command to the selected output implementation."""
        output = output_for(device_id)
        if output and device_id:
            await output.command(command, device_id, **kwargs)
        else:
            await playback.command(command, device_id=device_id, **kwargs)

    def save_selected_device(device_id: str) -> None:
        """Persist the preferred output atomically with owner-only permissions."""
        config.selected_device_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = config.selected_device_path.with_suffix(".tmp")
        temporary.write_text(device_id)
        os.chmod(temporary, 0o600)
        temporary.replace(config.selected_device_path)

    artwork_cache: dict[str, str] = {}

    async def resolve_artwork(player: dict[str, Any]) -> None:
        """Fill in album artwork for a local output using the provider."""
        track_id = player.pop("spotify_track_id", None)
        if not track_id or not playback.connected:
            return
        if track_id in artwork_cache:
            player["artwork"] = artwork_cache[track_id]
            return
        try:
            url = await playback.track_artwork(track_id)
        except Exception:
            LOGGER.warning("Could not resolve artwork for track %s", track_id, exc_info=True)
            return
        if url:
            artwork_cache[track_id] = url
            player["artwork"] = url

    async def resolve_playback_context() -> tuple[str | None, bool | None]:
        """Resolve the context to start on a newly selected output."""
        if watcher.current_config:
            return watcher.current_config.uri, watcher.current_config.shuffle
        if playback.connected:
            try:
                state = await playback.state()
            except Exception:
                state = None
            context_uri = state.get("context_uri") if state else None
            if context_uri:
                return context_uri, None
        return None, None

    async def pause_active_spotify_device() -> None:
        """Pause the currently playing Spotify device before switching outputs."""
        if not playback.connected:
            return
        try:
            state = await playback.state()
        except Exception:
            return
        if state and state.get("is_playing"):
            try:
                await playback.command("pause")
            except Exception:
                LOGGER.warning("Could not pause the previous Spotify device", exc_info=True)

    async def transfer_target(device_id: str) -> str:
        """Move playback to a Spotify Connect device or a local output."""
        output = output_for(device_id)
        if output is None:
            await playback.command("transfer", device_id=device_id)
            return "Transferred playback"
        context_uri, shuffle = await resolve_playback_context()
        if context_uri is None:
            raise OutputError(
                "Nothing to play on this device yet — insert a floppy or start "
                "Spotify playback first"
            )
        await pause_active_spotify_device()
        await output.play_context(context_uri, device_id, shuffle)
        return "Now playing on the selected speaker"

    async def play_disk(disk_config: Any, path: Path) -> None:
        """Start playback when the disk watcher emits a valid instruction."""
        if disk_config.provider != playback.name:
            raise RuntimeError(f"Provider {disk_config.provider!r} is not installed")
        LOGGER.info("Playing %s from %s", disk_config.uri, path)
        await play_target(disk_config.uri, selected_device_id, disk_config.shuffle)

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
        if isinstance(exc, OutputError):
            return HTTPException(status_code=409, detail=message)
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
        output = output_for(selected_device_id)
        if output and selected_device_id:
            try:
                player = await output.state(selected_device_id)
                await resolve_artwork(player)
            except Exception as exc:  # keep kiosk useful during provider outages
                error = str(exc)
        elif playback.connected:
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
            "selected_device_id": selected_device_id,
            "player": player,
            "error": error,
        }

    @app.get("/api/devices")
    async def devices() -> dict[str, Any]:
        """List playback targets from the active provider."""
        results = await asyncio.gather(
            playback.devices(),
            *(output.devices() for output in local_outputs),
            return_exceptions=True,
        )
        device_list: list[dict[str, Any]] = []
        warnings = []
        for result in results:
            if isinstance(result, BaseException):
                warnings.append(str(result))
            else:
                device_list.extend(result)
        for device in device_list:
            device["selected"] = device.get("id") == selected_device_id
        if not device_list and warnings:
            raise provider_error(RuntimeError("; ".join(warnings)))
        return {"devices": device_list, "warnings": warnings}

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
            device_id = request.device_id or selected_device_id
            context_uri = request.context_uri
            if not context_uri and watcher.current_config:
                context_uri = watcher.current_config.uri
            if context_uri:
                shuffle = request.shuffle
                if shuffle is None and watcher.current_config:
                    shuffle = watcher.current_config.shuffle
                await play_target(context_uri, device_id, shuffle)
            else:
                await command_target("resume", device_id)
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/pause", status_code=204)
    async def pause(request: DeviceRequest) -> None:
        """Pause playback."""
        try:
            await command_target("pause", request.device_id or selected_device_id)
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/next", status_code=204)
    async def next_track(request: DeviceRequest) -> None:
        """Skip to the next track."""
        try:
            await command_target("next", request.device_id or selected_device_id)
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/previous", status_code=204)
    async def previous_track(request: DeviceRequest) -> None:
        """Return to the previous track."""
        try:
            await command_target("previous", request.device_id or selected_device_id)
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/shuffle", status_code=204)
    async def shuffle(request: ShuffleRequest) -> None:
        """Set provider shuffle mode."""
        try:
            await command_target(
                "shuffle", request.device_id or selected_device_id, enabled=request.enabled
            )
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/volume", status_code=204)
    async def volume(request: VolumeRequest) -> None:
        """Set the active playback device volume."""
        try:
            await command_target(
                "volume",
                request.device_id or selected_device_id,
                volume_percent=request.volume_percent,
            )
        except Exception as exc:
            raise provider_error(exc) from exc

    @app.post("/api/transfer")
    async def transfer(request: DeviceRequest) -> dict[str, str]:
        """Transfer playback to a selected device and persist the choice."""
        nonlocal selected_device_id
        if not request.device_id:
            raise HTTPException(status_code=422, detail="device_id is required")
        try:
            message = await transfer_target(request.device_id)
            selected_device_id = request.device_id
            save_selected_device(request.device_id)
            return {"message": message}
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
