"""Tests for floppy drive effect logic (physical reads and track-end detection)."""

import os

from floppify.floppy import BLOCK_SIZE, FloppyThumper, near_track_end, track_identity


def test_thump_uses_direct_reads_across_disk(monkeypatch) -> None:
    """Tactile reads bypass the page cache and alternate across the disk."""
    opened: list[tuple[str, int]] = []
    offsets: list[int] = []

    monkeypatch.setattr(
        os,
        "open",
        lambda path, flags: opened.append((path, flags)) or 9,
    )
    monkeypatch.setattr(os, "lseek", lambda *_args: BLOCK_SIZE * 100)
    monkeypatch.setattr(
        os,
        "preadv",
        lambda _fd, _buffers, offset: offsets.append(offset) or BLOCK_SIZE,
    )
    monkeypatch.setattr(os, "close", lambda _fd: None)

    FloppyThumper(device="/dev/test", seeks=4)._thump()

    assert opened[0][0] == "/dev/test"
    assert opened[0][1] & getattr(os, "O_DIRECT", 0) == getattr(os, "O_DIRECT", 0)
    assert offsets == [0, BLOCK_SIZE * 99, BLOCK_SIZE, BLOCK_SIZE * 98]


def test_track_identity_prefers_spotify_track_id() -> None:
    player = {"spotify_track_id": "abc123", "track": "T", "album": "A", "artists": "B"}
    assert track_identity(player) == "abc123"
    assert track_identity({"track": "T", "album": "A", "artists": "B"}) == "T|A|B"


def test_near_track_end_thumps_once_per_track() -> None:
    near = {
        "is_playing": True,
        "duration_ms": 100000,
        "progress_ms": 99500,
        "track": "T",
        "album": "A",
        "artists": "B",
    }
    should, last = near_track_end(near, None)
    assert should is True
    assert last == "T|A|B"
    # Same track still near the end: no repeat.
    should, last = near_track_end(near, "T|A|B")
    assert should is False
    assert last == "T|A|B"


def test_near_track_end_resets_when_away_from_end() -> None:
    playing = {
        "is_playing": True,
        "duration_ms": 100000,
        "progress_ms": 0,
        "track": "T",
        "album": "A",
        "artists": "B",
    }
    # A restart or new track away from the end resets, allowing a repeat thump.
    should, last = near_track_end(playing, "T|A|B")
    assert should is False
    assert last is None


def test_near_track_end_ignores_paused_and_stopped() -> None:
    paused = {
        "is_playing": False,
        "duration_ms": 100000,
        "progress_ms": 99500,
        "track": "T",
        "album": "A",
        "artists": "B",
    }
    assert near_track_end(paused, None) == (False, None)
    assert near_track_end(None, None) == (False, None)


def test_near_track_end_requires_positive_duration() -> None:
    playing = {"is_playing": True, "duration_ms": 0, "progress_ms": 0, "track": "T"}
    assert near_track_end(playing, None) == (False, None)


def test_near_track_end_window_boundary() -> None:
    at_edge = {
        "is_playing": True,
        "duration_ms": 2000,
        "progress_ms": 1000,
        "track": "T",
        "album": "A",
        "artists": "B",
    }
    assert near_track_end(at_edge, None, window_ms=1000) == (True, "T|A|B")

    outside = {
        "is_playing": True,
        "duration_ms": 2000,
        "progress_ms": 900,
        "track": "T",
        "album": "A",
        "artists": "B",
    }
    assert near_track_end(outside, None, window_ms=1000) == (False, None)
