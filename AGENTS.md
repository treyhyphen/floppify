# AGENTS.md

## Project shape

- Python 3.11+ FastAPI application under `src/floppify`.
- Provider-specific behavior belongs under `providers/` behind `PlaybackProvider`.
- The floppy file format is provider-neutral and versioned.
- Target hardware is a Raspberry Pi 3 B+ with an 800×480 DSI touch display, USB TEAC floppy drive, Labwc, and Chromium.

## Quality gates

Run `ruff check .` and `pytest` before delivery. For UI changes, render at 800×480 and inspect the screenshot. Never commit Spotify tokens, client IDs, passwords, or `.env` files.

## Delivery

After the initial empty-repository bootstrap, use feature branches and pull requests. The checked-in pre-push hook blocks direct main pushes when `core.hooksPath=.githooks` is configured.
