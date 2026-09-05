# Floppify

Floppify turns a 3½-inch floppy disk into a physical Spotify album or mixtape. Insert a disk containing `floppify.json`; the Raspberry Pi reads it and starts that Spotify album, playlist, or artist. An 800×480 touch interface provides play/pause, previous/next, shuffle, volume, and Spotify Connect device selection.

## Architecture

- **FastAPI backend** serves the kiosk and a provider-neutral playback API.
- **`PlaybackProvider` interface** keeps Spotify-specific OAuth and Web API calls isolated so Plex or another provider can be added later.
- **Disk watcher** polls mounted removable-media roots and triggers each newly inserted disk once.
- **Spotify OAuth with PKCE** requires only a public client ID—no client secret is stored on the Pi.
- **Raspotify/librespot** optionally exposes the Pi's 3.5 mm output as a Spotify Connect device named **Floppify**.
- **Labwc/Chromium kiosk** launches the touch interface automatically at graphical login.

Spotify playback control and Spotify Connect require a **Spotify Premium** account.

## Connect your Spotify account

### 1. Create a Spotify developer app

1. Open <https://developer.spotify.com/dashboard> and sign in.
2. Choose **Create app**.
3. Set any name/description, select **Web API**, and accept Spotify's terms.
4. In the app's settings, add this redirect URI exactly:

   ```text
   http://127.0.0.1:8000/auth/spotify/callback
   ```

   Spotify permits HTTP for loopback redirect addresses. The OAuth flow must therefore be completed in the browser running on the Pi's touchscreen.
5. Copy the app's **Client ID**. A client secret is not needed.

Spotify development-mode apps may require the account to be added under the dashboard's user-management section. Add the Spotify account there if authorization reports that the user is not registered.

### 2. Configure the Pi

On the Pi, edit the root-owned environment file:

```bash
sudo nano /etc/floppify.env
```

Set:

```dotenv
FLOPPIFY_SPOTIFY_CLIENT_ID=your_client_id_here
FLOPPIFY_SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/auth/spotify/callback
```

Then restart:

```bash
sudo systemctl restart floppify
```

### 3. Authorize from the touchscreen

1. Reboot or open `http://127.0.0.1:8000` in Chromium on the Pi.
2. Tap **Connect Spotify**.
3. Sign in and approve playback access.
4. Floppify stores the refresh token at `/var/lib/floppify/spotify-token.json` with owner-only permissions. It is never committed to Git.

## Make a Floppify disk

Find an album or playlist in Spotify, choose **Share → Copy link**, insert a formatted floppy, and run:

```bash
python3 scripts/write-floppy.py /media/$USER/DISK playlist \
  'https://open.spotify.com/playlist/PLAYLIST_ID' \
  --name 'Road Trip' --shuffle
```

For an album in its intended order:

```bash
python3 scripts/write-floppy.py /media/$USER/DISK album \
  'spotify:album:ALBUM_ID' --name 'Kind of Blue'
```

The resulting file is small enough for any normal 1.44 MB FAT floppy:

```json
{
  "version": 1,
  "provider": "spotify",
  "type": "playlist",
  "uri": "spotify:playlist:PLAYLIST_ID",
  "shuffle": true,
  "name": "Road Trip"
}
```

Supported `type` values are `playlist`, `album`, and `artist`. Remove/eject the disk before inserting another one.

## Playback devices and local audio

The device menu shows every device returned by Spotify Connect. Spotify only reports devices that have been active recently; open Spotify on a phone/desktop and start playback briefly if the list is empty.

Install the optional local Spotify Connect receiver:

```bash
sudo ./scripts/install-raspotify.sh
```

Then open Spotify on another device, select **Floppify** from the device picker, and choose **Floppify** in the kiosk. The default output is ALSA `hw:0,0`, the Pi's analog headphone jack. Change `/etc/raspotify/conf` if using a USB DAC or HDMI audio.

## Raspberry Pi installation

On a Pi running Raspberry Pi OS/Debian with Chromium and Labwc:

```bash
git clone https://github.com/treyhyphen/floppify.git
cd floppify
sudo ./scripts/install.sh
sudo ./scripts/install-raspotify.sh  # optional local output
sudo reboot
```

The installer:

- creates `/opt/floppify/.venv`;
- installs and starts `floppify.service`;
- creates `/etc/floppify.env` without overwriting an existing configuration;
- adds a Labwc kiosk command without replacing existing autostart commands.

Useful operations:

```bash
curl http://127.0.0.1:8000/api/health
systemctl status floppify
journalctl -u floppify -f
systemctl status raspotify
```

The interface also listens on the LAN at `http://PI_ADDRESS:8000`, but OAuth login should be completed on the Pi because of the loopback redirect URI.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
ruff check .
pytest
uvicorn floppify.main:app --reload
```

Configuration is environment-driven; see `.env.example`. No credentials, OAuth tokens, or disk contents belong in Git.

## Adding another music provider

Implement `PlaybackProvider` in `src/floppify/providers/`, register it in the application factory, and retain the normalized API contract (`devices`, `state`, `play_context`, and `command`). Disk files already carry a `provider` field, so future Plex or local-library support does not require changing the media format.

## License

MIT
