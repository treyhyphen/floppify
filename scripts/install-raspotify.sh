#!/bin/bash
# Install Raspotify as the Raspberry Pi's local Spotify Connect output.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/install-raspotify.sh" >&2
  exit 1
fi
ARCH=$(dpkg --print-architecture)
case "$ARCH" in arm64|armhf|amd64) ;; *) echo "Unsupported architecture: $ARCH" >&2; exit 1;; esac
RELEASE=$(python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen('https://api.github.com/repos/dtcooper/raspotify/releases/latest', timeout=20) as response:
    data = json.load(response)
assets = [a['browser_download_url'] for a in data['assets'] if a['name'].startswith('raspotify_')]
print('\n'.join(assets))
PY
)
URL=$(printf '%s\n' "$RELEASE" | grep "_${ARCH}\.deb$" | head -n1)
[[ -n "$URL" ]] || { echo "No Raspotify package found for $ARCH" >&2; exit 1; }
TMP=$(mktemp --suffix=.deb)
trap 'rm -f "$TMP"' EXIT
curl -fL "$URL" -o "$TMP"
apt-get install -y "$TMP"

CONF=/etc/raspotify/conf
set_config() {
  local key=$1 value=$2
  if grep -q "^${key}=" "$CONF"; then
    sed -i "s|^${key}=.*|${key}=\"${value}\"|" "$CONF"
  else
    printf '%s="%s"\n' "$key" "$value" >>"$CONF"
  fi
}
install -o root -g root -m 600 /dev/null "$CONF.tmp"
cat "$CONF" >"$CONF.tmp"
mv "$CONF.tmp" "$CONF"
set_config LIBRESPOT_NAME Floppify
set_config LIBRESPOT_BACKEND alsa
set_config LIBRESPOT_DEVICE hw:0,0
systemctl enable --now raspotify
systemctl restart raspotify
systemctl --no-pager --full status raspotify || true
