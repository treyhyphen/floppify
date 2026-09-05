#!/bin/bash
# Add an HTTPS reverse proxy so Spotify OAuth can return to a non-loopback address.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/install-https.sh [device-ip-or-hostname]" >&2
  exit 1
fi

PUBLIC_HOST=${1:-$(hostname -I | cut -d' ' -f1)}
[[ -n "$PUBLIC_HOST" ]] || { echo "Could not determine the device address" >&2; exit 1; }
CERT_DIR=/etc/floppify/tls
SAFE_HOST=${PUBLIC_HOST//[^A-Za-z0-9_.-]/_}
CERT="$CERT_DIR/${SAFE_HOST}.crt"
KEY="$CERT_DIR/${SAFE_HOST}.key"
SITE=/etc/nginx/sites-available/floppify
REDIRECT_URI="https://${PUBLIC_HOST}/auth/spotify/callback"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y nginx openssl
install -d -o root -g root -m 700 "$CERT_DIR"

if [[ "$PUBLIC_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  SUBJECT_ALT_NAME="IP:${PUBLIC_HOST}"
else
  SUBJECT_ALT_NAME="DNS:${PUBLIC_HOST}"
fi

if [[ ! -s "$CERT" || ! -s "$KEY" ]]; then
  openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 825 \
    -keyout "$KEY" -out "$CERT" -subj "/CN=${PUBLIC_HOST}" \
    -addext "subjectAltName=${SUBJECT_ALT_NAME}"
fi
chmod 600 "$KEY"
chmod 644 "$CERT"

cat >"$SITE" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${PUBLIC_HOST};
    return 308 https://\$host\$request_uri;
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name ${PUBLIC_HOST};

    ssl_certificate ${CERT};
    ssl_certificate_key ${KEY};
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF
rm -f /etc/nginx/sites-enabled/default
ln -sfn "$SITE" /etc/nginx/sites-enabled/floppify

python3 - "$REDIRECT_URI" <<'PY'
import sys
from pathlib import Path

path = Path('/etc/floppify.env')
key = 'FLOPPIFY_SPOTIFY_REDIRECT_URI='
value = key + sys.argv[1]
lines = path.read_text().splitlines() if path.exists() else []
updated = [value if line.startswith(key) else line for line in lines]
if not any(line.startswith(key) for line in lines):
    updated.append(value)
temporary = path.with_suffix('.env.tmp')
temporary.write_text('\n'.join(updated) + '\n')
temporary.chmod(0o640)
temporary.replace(path)
PY
chown root:err /etc/floppify.env

nginx -t
systemctl enable nginx
systemctl restart nginx
systemctl restart floppify
printf 'HTTPS enabled at https://%s\nSpotify redirect URI: %s\n' "$PUBLIC_HOST" "$REDIRECT_URI"
printf 'Trust %s in the browser before starting Spotify authorization.\n' "$CERT"
