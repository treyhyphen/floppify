#!/bin/sh
# Launch the touch UI only after the backend is ready.
set -eu
URL="${FLOPPIFY_KIOSK_URL:-http://127.0.0.1:8000}"
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS "$URL/api/health" >/dev/null 2>&1; then
    exec /usr/bin/chromium \
      --kiosk \
      --noerrdialogs \
      --disable-infobars \
      --disable-session-crashed-bubble \
      --disable-translate \
      --overscroll-history-navigation=0 \
      --password-store=basic \
      --user-data-dir="$HOME/.config/floppify-chromium" \
      "$URL"
  fi
  i=$((i + 1))
  sleep 1
done
exit 1
