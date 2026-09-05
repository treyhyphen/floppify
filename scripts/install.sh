#!/bin/bash
# Install or upgrade Floppify on Raspberry Pi OS/Debian.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/install.sh" >&2
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR=/opt/floppify
INSTALL_USER=${FLOPPIFY_INSTALL_USER:-err}
USER_HOME=$(getent passwd "$INSTALL_USER" | cut -d: -f6)

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv curl

install -d -o root -g root -m 755 "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/src" "$INSTALL_DIR/.venv"
cp -a "$SOURCE_DIR/src" "$SOURCE_DIR/pyproject.toml" "$SOURCE_DIR/README.md" "$INSTALL_DIR/"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --disable-pip-version-check "$INSTALL_DIR"
chmod -R a+rX "$INSTALL_DIR"

install -d -o "$INSTALL_USER" -g "$INSTALL_USER" -m 700 /var/lib/floppify
if [[ ! -e /etc/floppify.env ]]; then
  install -o root -g "$INSTALL_USER" -m 640 "$SOURCE_DIR/.env.example" /etc/floppify.env
fi
install -o root -g root -m 644 "$SOURCE_DIR/deploy/floppify.service" /etc/systemd/system/floppify.service
install -o root -g root -m 755 "$SOURCE_DIR/deploy/launch-kiosk.sh" /usr/local/bin/floppify-kiosk
install -o root -g root -m 755 "$SOURCE_DIR/scripts/floppify-mounter.py" /usr/local/bin/floppify-mounter
install -o root -g root -m 644 "$SOURCE_DIR/deploy/floppify-mounter.service" /etc/systemd/system/floppify-mounter.service
install -o root -g root -m 755 "$SOURCE_DIR/scripts/floppify-media-changed" /usr/local/bin/floppify-media-changed
install -o root -g root -m 644 "$SOURCE_DIR/deploy/99-floppify.rules" /etc/udev/rules.d/99-floppify.rules

install -d -o "$INSTALL_USER" -g "$INSTALL_USER" -m 755 "$USER_HOME/.config/labwc"
AUTOSTART="$USER_HOME/.config/labwc/autostart"
touch "$AUTOSTART"
if ! grep -qF '/usr/local/bin/floppify-kiosk' "$AUTOSTART"; then
  printf '\n# Floppify touchscreen kiosk\n/usr/local/bin/floppify-kiosk &\n' >>"$AUTOSTART"
fi
chown "$INSTALL_USER:$INSTALL_USER" "$AUTOSTART"
chmod 755 "$AUTOSTART"

systemctl daemon-reload
systemctl enable floppify.service
systemctl restart floppify.service
systemctl enable floppify-mounter.service
systemctl restart floppify-mounter.service
udevadm control --reload-rules
udevadm trigger --subsystem-match=block
systemctl --no-pager --full status floppify.service || true
printf '\nFloppify is installed. Configure /etc/floppify.env, then run:\n'
printf '  sudo systemctl restart floppify\n'
printf 'The kiosk launches at the next graphical login/reboot.\n'
