# Floppify

Floppify turns a 3½-inch floppy disk into a physical Spotify album or mixtape. Insert a disk containing `floppify.json`; the Raspberry Pi reads it and starts that Spotify album, playlist, or artist. An 800×480 touch interface provides play/pause, previous/next, shuffle, volume, and Spotify Connect device selection.

## Architecture

- **FastAPI backend** serves the kiosk and a provider-neutral playback API.
- **`PlaybackProvider` interface** keeps Spotify-specific OAuth and Web API calls isolated so Plex or another provider can be added later.
- **Disk watcher** polls mounted removable-media roots, triggers each newly inserted disk once, and stops playback (clearing any local queue) on eject.
- **Floppy auto-mount** (`floppify-mounter` service) actively probes the USB floppy drive and mounts it read-only on insert, unmounting and stopping playback on eject. Because the kernel only re-checks floppy media when the device is opened, the mounter opens the device on a fast cycle to force a media re-check.
- **Spotify OAuth with PKCE** requires only a public client ID—no client secret is stored on the Pi.
- **Raspotify/librespot** optionally exposes the Pi's 3.5 mm output as a Spotify Connect device named **Floppify**.
- **Labwc/Chromium kiosk** launches the touch interface automatically at graphical login.

Spotify playback control and Spotify Connect require a **Spotify Premium** account.

## Connect your Spotify account

### 1. Create a Spotify developer app

1. Open <https://developer.spotify.com/dashboard> and sign in.
2. Choose **Create app**.
3. Set any name/description, select **Web API**, and accept Spotify's terms.
4. If authorizing from another computer or phone, add this redirect URI exactly:

   ```text
   https://172.16.0.47/auth/spotify/callback
   ```

   Spotify requires HTTPS for every non-loopback redirect. Floppify's HTTPS installer creates a local certificate; visit `https://172.16.0.47` and accept/trust that certificate before starting authorization. For touchscreen-only authorization, the loopback URI `http://127.0.0.1:8000/auth/spotify/callback` remains valid.
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
FLOPPIFY_SPOTIFY_REDIRECT_URI=https://172.16.0.47/auth/spotify/callback
```

Then install the HTTPS proxy and restart Floppify:

```bash
sudo ./scripts/install-https.sh 172.16.0.47
```

### 3. Authorize Spotify

Open `https://172.16.0.47`, accept the local certificate warning, then tap **Connect Spotify**. The browser starting authorization must be able to open the configured redirect URI.

For touchscreen-only authorization, you can instead retain the loopback redirect and open `http://127.0.0.1:8000` on the Pi.

After approval, Floppify stores the refresh token at `/var/lib/floppify/spotify-token.json` with owner-only permissions. It is never committed to Git.

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

On the Pi, the `floppify-mounter` service actively probes the USB floppy drive and mounts it at `/mnt/floppify` automatically when a disk is inserted, and unmounts + stops playback on eject, so no manual mounting is needed. Ejecting the disk stops playback and clears the active queue. USB Mass Storage is host-polled, so there is no media-change interrupt to key off; the mounter polls fast while a disk is present and backs off while idle. The device, mount point, and poll rates are configurable via `FLOPPIFY_FLOPPY_DEVICE` (default `/dev/sda`), `FLOPPIFY_FLOPPY_MOUNT` (default `/mnt/floppify`), `FLOPPIFY_FLOPPY_POLL` (default `0.3`), and `FLOPPIFY_FLOPPY_POLL_IDLE` (default `1.5`).

## Playback devices and local audio

The device menu combines Spotify Connect devices with Sonos rooms discovered directly over the local network. Spotify only reports Connect devices that have been active recently; local Sonos discovery does not depend on Spotify's incomplete device list.

### Sonos

Sonos support is enabled by default. Rooms are labeled `• Sonos` in the picker, and the selected room is saved as the preferred output for future disk insertions. Album and playlist disks replace that Sonos group's queue using the Spotify account already linked in the Sonos app. Artist disks remain Spotify Connect-only.

The Pi and speakers must be reachable across any VLANs, including multicast/SSDP reflection. Set `FLOPPIFY_SONOS_ENABLED=false` to disable discovery.

### Pi audio through Spotify Connect

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
sudo ./scripts/install-https.sh 172.16.0.47  # OAuth from another browser
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

The backend listens on `http://PI_ADDRESS:8000`. After running `install-https.sh`, use `https://PI_ADDRESS` for LAN access and Spotify authorization. Spotify's redirect requirements are documented at <https://developer.spotify.com/documentation/web-api/concepts/redirect_uri>.

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
