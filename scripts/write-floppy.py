#!/usr/bin/env python3
"""Write a validated Floppify JSON instruction to an already-mounted floppy."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def spotify_uri(value: str, expected_type: str) -> str:
    """Normalize and validate a Spotify context URI or shared URL."""
    if value.startswith("spotify:"):
        parts = value.split(":")
        if len(parts) == 3 and parts[1] == expected_type and parts[2]:
            return value
    parsed = urlparse(value)
    parts = parsed.path.strip("/").split("/")
    if parsed.netloc == "open.spotify.com" and len(parts) >= 2 and parts[-2] == expected_type:
        return f"spotify:{expected_type}:{parts[-1]}"
    raise ValueError(f"Expected a Spotify {expected_type} URI or URL")


def main() -> None:
    """Parse arguments and safely write floppify.json."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mount", type=Path, help="mounted floppy directory")
    parser.add_argument("type", choices=("album", "playlist", "artist"))
    parser.add_argument("uri", help="Spotify URI or open.spotify.com URL")
    parser.add_argument("--name")
    parser.add_argument("--shuffle", action="store_true")
    args = parser.parse_args()
    if not args.mount.is_dir():
        parser.error(f"mount is not a directory: {args.mount}")
    payload = {
        "version": 1,
        "provider": "spotify",
        "type": args.type,
        "uri": spotify_uri(args.uri, args.type),
        "shuffle": args.shuffle,
        "name": args.name,
    }
    target = args.mount / "floppify.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    print(target)


if __name__ == "__main__":
    main()
