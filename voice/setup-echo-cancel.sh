#!/usr/bin/env bash
# Set up PipeWire WebRTC echo cancellation on the barge-in mic.
#
# During TTS the barge-in mic (USB PnP) hears Luna's own voice at 8000-26000
# mean-abs (near clipping) while a user saying the wake word reaches roughly
# 1000-5000, so the wake word scores 0.00 and barge-in never fires. This adds
# a WebRTC AEC that takes that mic as capture and the default sink's monitor
# as the echo reference (monitor.mode, so pw-play needs no rerouting), and
# exposes the cleaned signal as the PipeWire source luna_ec_source. The ALSA
# PCM luna_barge points sounddevice at it.
#
# It also takes the mic off max gain and turns its Auto Gain Control off: the
# AEC can't model an echo that is clipped or being pumped by AGC.
#
# The main mic (S330, default source) and the default sink are left alone.
#
# Run as the user that runs luna-voice (user PipeWire session), then set
# BARGE_IN_DEVICE=luna_barge in voice/.env and: sudo systemctl restart luna-voice
# Safe to re-run.
set -euo pipefail

MIC_NODE="${LUNA_EC_MIC:-alsa_input.usb-C-Media_Electronics_Inc._USB_PnP_Sound_Device-00.analog-mono}"
# PipeWire (cubic) volume for the mic; 0.56 is ~15 dB below its +23.8 dB max
MIC_VOLUME="${LUNA_EC_MIC_VOLUME:-0.56}"

CONF_DIR="$HOME/.config/pipewire/pipewire.conf.d"
mkdir -p "$CONF_DIR"
cat > "$CONF_DIR/luna-echo-cancel.conf" << EOF
# Luna: echo-cancelled barge-in mic (voice/setup-echo-cancel.sh)
context.modules = [
  { name = libpipewire-module-echo-cancel
    args = {
      library.name = aec/libspa-aec-webrtc
      monitor.mode = true
      audio.channels = 1
      audio.position = [ MONO ]
      # These streams exist before WirePlumber has brought up the USB devices.
      # dont-fallback alone makes WirePlumber destroy a stream whose target is
      # missing, which unloads the whole module; linger makes it wait instead.
      capture.props = {
        node.name = "luna_ec_capture"
        target.object = "$MIC_NODE"
        node.dont-fallback = true
        node.linger = true
      }
      source.props = {
        node.name = "luna_ec_source"
        node.description = "Luna Barge-in Mic (echo-cancelled)"
        priority.session = 0
      }
      sink.props = {
        node.name = "luna_ec_reference"
        node.linger = true
      }
      # NS and transient suppression erased the user's wake word while Luna
      # was talking (double-talk); the AEC alone already removes the echo.
      aec.args = {
        webrtc.gain_control = false
        webrtc.noise_suppression = false
        webrtc.transient_suppression = false
      }
    }
  }
]
EOF

ASOUNDRC="$HOME/.asoundrc"
if ! grep -qs "pcm.luna_barge" "$ASOUNDRC"; then
    cat >> "$ASOUNDRC" << 'EOF'

# Luna: echo-cancelled barge-in mic for sounddevice (voice/setup-echo-cancel.sh)
pcm.luna_barge {
    type pipewire
    capture_node "luna_ec_source"
    hint { show on description "Luna barge-in mic (echo-cancelled)" }
}
EOF
fi

systemctl --user restart wireplumber pipewire
sleep 3

# Prints "<ec source id> <mic id> <mic ALSA card>", "-" for anything missing.
lookup() {
    pw-dump | python3 -c '
import json, sys
nodes = {o["info"]["props"].get("node.name"): o for o in json.load(sys.stdin)
         if o.get("type") == "PipeWire:Interface:Node"}
ec, mic = nodes.get("luna_ec_source"), nodes.get(sys.argv[1])
print(ec["id"] if ec else "-", mic["id"] if mic else "-",
      mic["info"]["props"].get("alsa.card", "-") if mic else "-")
' "$MIC_NODE"
}

for i in $(seq 1 20); do
    ids=$(lookup 2>/dev/null) || ids="- - -"
    read -r ec_id mic_id mic_card <<< "$ids"
    [ "$ec_id" != "-" ] && [ "$mic_id" != "-" ] && break
    sleep 1
done

if [ "$mic_id" = "-" ]; then
    echo "ERROR: mic $MIC_NODE not found (plugged in? set LUNA_EC_MIC to its node.name)" >&2
    exit 1
fi
if [ "$ec_id" = "-" ]; then
    # The module unloads itself (logging only at info level) if a stream drops
    echo "ERROR: luna_ec_source missing; echo-cancel module not loaded or unloaded itself." >&2
    echo "Debug: PIPEWIRE_DEBUG=3 pipewire  (after: systemctl --user stop pipewire pipewire.socket)" >&2
    exit 1
fi

wpctl set-volume "$mic_id" "$MIC_VOLUME"
if [ "$mic_card" != "-" ]; then
    amixer -q -c "$mic_card" cset name='Auto Gain Control' off \
        || echo "WARN: could not turn off Auto Gain Control on ALSA card $mic_card" >&2
    # Persist the mixer state so AGC stays off after a reboot
    sudo -n alsactl store 2>/dev/null \
        || echo "NOTE: run 'sudo alsactl store' to keep AGC off across reboots"
fi

if wpctl inspect @DEFAULT_AUDIO_SOURCE@ | grep -q 'node.name = "luna_ec_source"'; then
    echo "WARN: luna_ec_source became the default source; the main mic should stay the S330" >&2
fi

echo "luna_ec_source is node $ec_id (mic node $mic_id, volume $MIC_VOLUME, AGC off)"
echo "Now set BARGE_IN_DEVICE=luna_barge in voice/.env and run: sudo systemctl restart luna-voice"
