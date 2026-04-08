# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Luna** - Self-hosted voice assistant replacing Alexa with local LLMs, web search, and home automation integration.

## Architecture

**k3s cluster with 5 nodes:**
- **raspberrypi** (192.168.0.167) — control-plane, primary
- **raspberrypi2** (192.168.0.146) — apps workloads
- **raspberrypi3** (192.168.0.111) — control-plane, runs luna-brain pod
- **raspberrypi4** (192.168.0.116) — control-plane
- **headless-gpu** (192.168.0.150) — GPU node (AMD RX 7900 XT), runs Ollama/faster-whisper/SearXNG

**Voice service** runs bare metal on raspberrypi3 (not containerized — requires USB audio hardware access).

**Data flow**: Wake word → Audio capture → Whisper transcription (k3s) → Brain/LLM (k3s) → TTS response (local Piper) → Playback

## Project Structure

```
luna-voice-assistant/
├── brain/                    # FastAPI service (runs in k3s, calls remote services)
│   ├── main.py              # /ask and /ask/stream endpoints
│   ├── prompts.py           # System prompt + tool definitions
│   ├── config.py            # Environment-based configuration
│   ├── llm/                 # Provider implementations + fallback chain
│   └── tools/               # Tool implementations
│       ├── web_search.py    # SearXNG
│       ├── prometheus.py    # PromQL queries
│       ├── timescaledb.py   # Sensor data SQL queries
│       ├── mqtt.py          # MQTT publish
│       ├── timers.py        # Persistent timers
│       ├── kasa.py          # Kasa + WiZ light control
│       └── weather.py       # Open-Meteo weather queries
├── voice/                    # Voice assistant (runs on Pi)
│   ├── main.py              # Main loop
│   ├── audio.py             # Mic recording with sounddevice
│   ├── wakeword.py          # OpenWakeWord detection
│   ├── stt.py               # Whisper transcription
│   ├── tts.py               # Piper TTS + pw-play
│   ├── brain_client.py      # HTTP client to brain service
│   ├── metrics_server.py    # Prometheus /metrics endpoint
│   └── luna-voice.service   # Systemd unit for bare-metal runtime
└── docs/
    └── broker-topics-known.txt
```

## Services & Endpoints

**k3s namespaces:**

| Service | Namespace | ClusterIP Port | NodePort | Purpose |
|---------|-----------|---------------|----------|---------|
| luna-brain | apps | 8000 | — | FastAPI, routes to LLM |
| faster-whisper | ai | 8000 | 30800 | Speech-to-text |
| searxng | ai | 8080 | 30089 | Web search |
| llm-gateway | ai | 4000 | — | LLM routing |
| mosquitto | iot | 1883 | — | MQTT broker |
| prometheus | monitoring | 9090 | — | System metrics |
| timescaledb | data | 5432 | — | Time-series data |

**Bare metal:**

| Service | Host | Purpose |
|---------|------|---------|
| Piper TTS | raspberrypi3 | Local binary ~/piper/piper |
| Voice assistant | raspberrypi3 | Wake word + audio + TTS |
| Ollama | 192.168.0.150 | LLM inference (qwen2.5:14b) |
| TimescaleDB | 192.168.0.146:5433 | Sensor data |

## Commands

```bash
# Start voice assistant (bare metal on raspberrypi3)
cd voice && source venv/bin/activate && python main.py

# Brain is a k3s deployment — manage via kubectl
kubectl get pods -n apps -l app.kubernetes.io/name=luna-brain
kubectl logs -n apps -l app.kubernetes.io/name=luna-brain -f

# Test brain directly (via ClusterIP from any k3s node)
curl -X POST http://luna-brain.apps.svc.cluster.local:8000/ask \
  -H "Content-Type: application/json" -d '{"text": "What time is it?"}'
```

## Building and Deploying (brain)

`docker` is not available on the cluster nodes (permission denied). Use `nerdctl` instead.

**Critical**: nerdctl's default namespace is invisible to k3s. You must build into the `k8s.io` namespace and then import the image into k3s's containerd store.

```bash
# 1. Build the image into the k8s.io namespace (NOT default nerdctl namespace)
sudo nerdctl --namespace k8s.io build --no-cache -t homelab-app-brain:latest ./brain/

# 2. Import into k3s containerd image store
sudo nerdctl --namespace k8s.io save homelab-app-brain:latest | sudo k3s ctr images import -

# 3. Restart the deployment to pick up the new image
kubectl rollout restart deploy/luna-brain -n apps
kubectl rollout status deploy/luna-brain -n apps --timeout=60s
```

**Notes**:
- `--no-cache` is required to avoid stale cached layers.
- The `nerdctl save | k3s ctr import` pipe is needed because nerdctl's k8s.io namespace and k3s's internal containerd store are separate registries.
- Image pull policy in the deployment must be `Never` (or `IfNotPresent`) so k3s uses the locally imported image.

## Sensor Data Schema

**Database**: `sensors`
**Table**: `esp_temperature`
**Columns**: device, celsius, fahrenheit, humidity (optional), time
**Devices**: Spa, Main-Cottage, Big-Garage, Small-Garage, Pump-House, Sauna, Shack-ICF, Weather-Station-Main

## Current Status

### ✅ Completed
- k3s cluster deployment (brain, faster-whisper, searxng, mosquitto, monitoring)
- Brain service with Ollama tool calling (qwen2.5:14b via OLLAMA_AUTO_MODEL)
- Tools: web_search, query_timescaledb, query_prometheus, mqtt_publish, timers, weather, light control
- LLM fallback chain: Ollama → Groq → Anthropic (FallbackProvider)
- Voice service with OpenWakeWord ("hey luna"), Whisper, Piper TTS
- Audio handling: Anker S330 USB speakerphone via PipeWire
- Barge-in support (interrupt TTS with wake word)
- Whisper hallucination filtering
- TimescaleDB sensor queries working
- Systemd service for resilient bare-metal voice runtime
- Structured JSON logging (Loki-compatible)

## USB Audio Setup (Anker PowerConf S330)

The Anker S330 USB speakerphone is the audio device for both mic input and speaker output. On the Pi 3, USB isochronous transfers can drop under sustained load, causing the audio capture stream to stall and hang `read_chunk()` indefinitely.

**Required udev rule** — must be installed on any new Pi running the voice service:

```bash
sudo tee /etc/udev/rules.d/99-usb-no-autosuspend.rules << 'EOF'
# Disable USB autosuspend for Anker PowerConf S330 to prevent audio stream stalls
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="291a", ATTR{idProduct}=="3308", ATTR{power/autosuspend_delay_ms}="-1", ATTR{power/control}="on"

# Disable autosuspend on USB root hubs (prevents cascading suspend of child devices)
ACTION=="add", SUBSYSTEM=="usb", ATTR{bDeviceClass}=="09", ATTR{power/control}="on"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=usb
```

**Why**: USB autosuspend (default 2s timeout) causes the xHCI controller to briefly suspend the device, which corrupts the isochronous audio capture stream. Kernel logs show `retire_capture_urb: callbacks suppressed` when this happens. The voice app has a 5-second watchdog timeout on audio reads (`READ_TIMEOUT_SECONDS` in `audio.py`) that auto-recovers by reopening the stream, but disabling autosuspend prevents the issue in the first place.

**Verify**:
```bash
# Should show autosuspend=-1, control=on
cat /sys/bus/usb/devices/1-1/power/autosuspend_delay_ms  # -1
cat /sys/bus/usb/devices/1-1/power/control                # on
```

## Configuration

Both services use `.env` files (not committed, see `.env.example`):

**brain** — configured via k3s deployment env vars (see `kubectl get deploy luna-brain -n apps -o yaml`):
- LLM_PROVIDER, OLLAMA_URL, OLLAMA_MODEL
- TIMESCALEDB_HOST, TIMESCALEDB_PORT, TIMESCALEDB_DATABASE, TIMESCALEDB_USER, TIMESCALEDB_PASSWORD
- SEARXNG_URL (cluster-internal: `searxng.ai.svc.cluster.local`)
- MQTT_BROKER (cluster-internal: `mosquitto.iot.svc.cluster.local`)
- LOCATION_CITY, LOCATION_REGION, LOCATION_COUNTRY, LOCATION_TIMEZONE, LOCATION_LAT, LOCATION_LON
- Secrets via k8s Secret `luna-brain-secrets`

**voice/.env** (uses k3s ClusterIPs — voice runs bare metal on a k3s node):
```
BRAIN_URL=http://<luna-brain-clusterip>:8000
WHISPER_URL=http://<faster-whisper-clusterip>:8000
PIPER_PATH=/home/aachten/piper/piper
PIPER_MODEL=/home/aachten/piper-voices/en_US-hfc_female-medium.onnx
WAKEWORD_ENGINE=openwakeword
WAKEWORD_THRESHOLD=0.5
VAD_THRESHOLD=0.0
STREAMING_STT_ENABLED=true
BARGE_IN_ENABLED=true
```

## Location Context

Property in Pembroke, Ontario, Canada (Eastern Time). Weather queries use this location.
