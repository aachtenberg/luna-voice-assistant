#!/usr/bin/env bash
# Set up PipeWire WebRTC echo cancellation for Luna barge-in.
#
# The Anker S330's mic picks up Luna's own TTS at ~6000-9000 mean-abs while
# user speech from across the room is ~100-1700, so the wake word is
# acoustically buried during playback. This routes all playback through a
# virtual sink that PipeWire's WebRTC AEC uses as its reference, and exposes
# a virtual source with that playback subtracted. Both are made the defaults,
# so pw-play and the voice app pick them up without code changes.
#
# Run as the user that runs luna-voice (uses the user PipeWire session),
# then: sudo systemctl restart luna-voice
set -euo pipefail

CONF_DIR="$HOME/.config/pipewire/pipewire.conf.d"
mkdir -p "$CONF_DIR"
cat > "$CONF_DIR/luna-echo-cancel.conf" << 'EOF'
# Luna: WebRTC echo cancellation so the wake word is audible during TTS.
context.modules = [
  { name = libpipewire-module-echo-cancel
    args = {
      aec.method = webrtc
      source.props = { node.name = "luna_ec_source" node.description = "Luna Echo-Cancelled Mic" }
      sink.props   = { node.name = "luna_ec_sink"   node.description = "Luna Echo-Cancel Playback" }
    }
  }
]
EOF

systemctl --user restart pipewire wireplumber
sleep 3

# Wait for the echo-cancel nodes, then make them the defaults.
for i in $(seq 1 10); do
    ids=$(pw-dump | python3 -c '
import json, sys
nodes = [o for o in json.load(sys.stdin) if o.get("type") == "PipeWire:Interface:Node"]
by = {o["info"]["props"].get("node.name"): o["id"] for o in nodes}
print(by.get("luna_ec_source") or "", by.get("luna_ec_sink") or "")
')
    src_id=$(echo "$ids" | awk '{print $1}')
    snk_id=$(echo "$ids" | awk '{print $2}')
    if [ -n "$src_id" ] && [ -n "$snk_id" ]; then
        wpctl set-default "$src_id"
        wpctl set-default "$snk_id"
        echo "Defaults set: luna_ec_source (id $src_id), luna_ec_sink (id $snk_id)"
        echo "Now run: sudo systemctl restart luna-voice"
        exit 0
    fi
    sleep 1
done

echo "ERROR: echo-cancel nodes did not appear; check 'journalctl --user -u pipewire'" >&2
exit 1
