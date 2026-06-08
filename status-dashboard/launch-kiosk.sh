#!/bin/sh
# Launch the Luna Voice status dashboard in Chromium kiosk mode.
# Run from within the labwc/Wayland session (WAYLAND_DISPLAY already set).
URL="http://localhost:8090"

# Wait for the status server to come up (it's a separate systemd service).
i=0
while [ "$i" -lt 30 ]; do
  if curl -sf "$URL/api/status" >/dev/null 2>&1; then break; fi
  i=$((i + 1))
  sleep 1
done

exec chromium --kiosk --ozone-platform=wayland \
  --app="$URL" \
  --user-data-dir="$HOME/.config/luna-kiosk" \
  --password-store=basic \
  --noerrdialogs --disable-infobars --no-first-run \
  --disable-session-crashed-bubble --check-for-update-interval=31536000 \
  --disable-features=Translate
