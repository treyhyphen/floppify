"""Tests for removable-media discovery."""

from pathlib import Path

import pytest

from floppify.disk import DiskWatcher


@pytest.mark.asyncio
async def test_disk_watcher_emits_new_valid_disk_once(tmp_path: Path) -> None:
    """A mounted disk should trigger once until it disappears and returns."""
    calls = []

    async def inserted(config, path):
        calls.append((config, path))

    disk = tmp_path / "desktop-user" / "MIXTAPE"
    disk.mkdir(parents=True)
    config_path = disk / "floppify.json"
    config_path.write_text(
        '{"version":1,"provider":"spotify","type":"playlist",'
        '"uri":"spotify:playlist:abc","shuffle":true,"name":"Road Trip"}'
    )
    watcher = DiskWatcher((tmp_path,), inserted)

    await watcher.scan_once()
    await watcher.scan_once()

    assert len(calls) == 1
    assert calls[0][0].name == "Road Trip"
    assert watcher.status()["inserted"] is True

    config_path.unlink()
    await watcher.scan_once()
    assert watcher.status()["inserted"] is False

    config_path.write_text(
        '{"provider":"spotify","type":"album","uri":"spotify:album:def"}'
    )
    await watcher.scan_once()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_disk_watcher_fires_eject_once(tmp_path: Path) -> None:
    """Ejecting a disk should fire the eject callback exactly once."""
    ejects = []

    async def inserted(config, path):
        return None

    async def ejected():
        ejects.append(True)

    disk = tmp_path / "MIXTAPE"
    disk.mkdir()
    config_path = disk / "floppify.json"
    config_path.write_text(
        '{"provider":"spotify","type":"playlist","uri":"spotify:playlist:abc"}'
    )
    watcher = DiskWatcher((tmp_path,), inserted, on_eject=ejected)

    await watcher.scan_once()
    assert ejects == []

    config_path.unlink()
    await watcher.scan_once()
    assert ejects == [True]

    # A second scan while still empty must not re-fire.
    await watcher.scan_once()
    assert ejects == [True]


@pytest.mark.asyncio
async def test_disk_watcher_reports_invalid_config(tmp_path: Path) -> None:
    """Malformed disk data should be visible without invoking playback."""
    calls = []

    async def inserted(config, path):
        calls.append((config, path))

    disk = tmp_path / "BROKEN"
    disk.mkdir()
    (disk / "floppify.json").write_text("not json")
    watcher = DiskWatcher((tmp_path,), inserted)

    await watcher.scan_once()

    assert calls == []
    assert "Invalid floppify.json" in str(watcher.status()["error"])


@pytest.mark.asyncio
async def test_disk_watcher_preserves_config_when_playback_fails(tmp_path: Path) -> None:
    """Provider failures should not be mislabeled as malformed disk files."""

    async def inserted(config, path):
        raise RuntimeError("Spotify is not connected")

    disk = tmp_path / "MIXTAPE"
    disk.mkdir()
    (disk / "floppify.json").write_text(
        '{"provider":"spotify","type":"playlist","uri":"spotify:playlist:abc"}'
    )
    watcher = DiskWatcher((tmp_path,), inserted)

    await watcher.scan_once()

    status = watcher.status()
    assert isinstance(status["config"], dict)
    assert status["config"]["uri"] == "spotify:playlist:abc"
    assert status["error"] == "Playback failed: Spotify is not connected"
