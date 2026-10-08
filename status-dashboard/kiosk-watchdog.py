#!/usr/bin/env python3
"""Restart the kiosk Chromium when it is alive but rendering a blank white page.

lwrespawn only restarts Chromium when it *exits*. The failure seen on
raspberrypi5 (2026-08-31, and again 2026-10-08 after the cold-boot guard in
launch-kiosk.sh had already run) is a live Chromium with live renderers that
paints nothing but white, which lwrespawn cannot see.

So: screenshot the compositor with grim, and if the frame is almost entirely
white twice in a row, SIGTERM the kiosk's browser process and let lwrespawn
start a fresh one. The dashboard is dark, so a white frame is never a
legitimate state. A black frame is not treated as blank: that is what a
blanked or switched-off display looks like.

Run by kiosk-watchdog.timer as a systemd --user unit, which supplies
WAYLAND_DISPLAY and XDG_RUNTIME_DIR. Stdlib only.
"""

import os
import signal
import subprocess
import sys
import time

PROFILE = os.path.expanduser("~/.config/luna-kiosk")
WHITE = 240          # a channel at or above this counts as white
BLANK_FRACTION = 0.90  # healthy dashboard measures 0%; the real failure ~100%
GRACE_SECONDS = 120  # leave a freshly launched browser time to paint
CONFIRM_DELAY = 15   # second look, so a mid-navigation flash is not a restart


def log(msg):
    print(msg, flush=True)


def kiosk_browser_pid():
    """The kiosk's top-level Chromium: our profile, and no --type= (not a child)."""
    profile_arg = "--user-data-dir=" + PROFILE
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            # Chromium rewrites its process title as one space-joined string,
            # so the NUL separators are gone; split on whitespace instead.
            with open(f"/proc/{name}/cmdline", "rb") as f:
                args = f.read().replace(b"\0", b" ").decode(errors="replace").split()
        except OSError:
            continue
        if not args or not args[0].endswith("/chromium"):
            continue
        if profile_arg in args and not any(a.startswith("--type=") for a in args):
            return int(name)
    return None


def process_age(pid):
    clk = os.sysconf("SC_CLK_TCK")
    with open(f"/proc/{pid}/stat") as f:
        # Field 22 (starttime); split after the ")" so a comm with spaces is safe.
        start_ticks = int(f.read().rsplit(")", 1)[1].split()[19])
    with open("/proc/uptime") as f:
        uptime = float(f.read().split()[0])
    return uptime - start_ticks / clk


def white_fraction():
    ppm = subprocess.run(["grim", "-t", "ppm", "-s", "0.25", "-"],
                         check=True, capture_output=True, timeout=20).stdout
    # P6 header: magic, width, height, maxval, then one whitespace byte.
    fields, pos = [], 0
    while len(fields) < 4:
        while ppm[pos:pos + 1].isspace():
            pos += 1
        end = pos
        while not ppm[end:end + 1].isspace():
            end += 1
        fields.append(ppm[pos:end])
        pos = end
    if fields[0] != b"P6" or fields[3] != b"255":
        raise ValueError(f"unexpected grim output header {fields!r}")
    pixels = ppm[pos + 1:]
    total = len(pixels) // 3
    white = sum(1 for i in range(0, total * 3, 3)
                if pixels[i] >= WHITE and pixels[i + 1] >= WHITE and pixels[i + 2] >= WHITE)
    return white / total if total else 0.0


def main():
    pid = kiosk_browser_pid()
    if pid is None:
        # Also what a broken process match looks like, so say it every run.
        log("kiosk chromium not running; lwrespawn owns that case")
        return 0
    if process_age(pid) < GRACE_SECONDS:
        return 0

    frac = white_fraction()
    if frac < BLANK_FRACTION:
        return 0
    log(f"kiosk frame {frac:.0%} white; confirming in {CONFIRM_DELAY}s")
    time.sleep(CONFIRM_DELAY)
    if kiosk_browser_pid() != pid:
        return 0
    frac = white_fraction()
    if frac < BLANK_FRACTION:
        log(f"kiosk recovered on its own ({frac:.0%} white)")
        return 0

    log(f"kiosk blank ({frac:.0%} white) with chromium pid {pid} alive; "
        "sending SIGTERM so lwrespawn relaunches it")
    os.kill(pid, signal.SIGTERM)
    return 0


if __name__ == "__main__":
    sys.exit(main())
