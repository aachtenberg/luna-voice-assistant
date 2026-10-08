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

# /usr/bin/chromium injects --js-flags=--no-decommit-pooled-pages on aarch64
# with 16K pages (Debian #1089647). V8 in Chromium 147 no longer knows that
# flag, so every renderer exits at startup -> blank white kiosk. Chromium's
# command line takes the LAST occurrence of a switch, and the wrapper puts its
# flags before ours, so re-specifying --js-flags empty neutralizes it.
#
# Built with `set --` rather than repeated inline, so the warm-up launch below
# and the real one cannot drift apart.
set -- --kiosk --ozone-platform=wayland \
  --js-flags= \
  --app="$URL" \
  --user-data-dir="$HOME/.config/luna-kiosk" \
  --password-store=basic \
  --noerrdialogs --disable-infobars --no-first-run \
  --disable-session-crashed-bubble --check-for-update-interval=31536000 \
  --disable-features=Translate

# Cold-boot guard. On 2026-08-31 the kiosk came up as a blank white surface
# after a reboot even though the status server was already answering and these
# exact flags were in use — Chromium lost the render on the cold boot, and an
# identical relaunch 30 minutes later was fine. lwrespawn only respawns on
# *exit*, so a live-but-blank Chromium is invisible to it; it sat white until
# a human noticed.
#
# So: once per session, throw the first Chromium away after WARMUP seconds and
# start a clean one. Costs a flicker shortly after boot and removes the failure
# mode. The marker lives in XDG_RUNTIME_DIR, which is emptied on logout, so
# this runs once per session and never on a later lwrespawn respawn.
#
# `timeout` (not a background job + kill) keeps this bounded: SIGTERM at
# WARMUP, SIGKILL 5s after that, and it reaps the process, so the kiosk can
# never be left with no browser at all. If Chromium exits on its own before
# WARMUP, timeout returns early and the real launch happens immediately.
WARMUP=60
MARKER="${XDG_RUNTIME_DIR:-/tmp}/luna-kiosk-warmed"
if [ ! -e "$MARKER" ]; then
  : > "$MARKER"
  timeout -k 5 "$WARMUP" chromium "$@"
  # Let the browser process release the profile's SingletonLock before the
  # replacement claims the same --user-data-dir.
  sleep 2
fi

exec chromium "$@"
