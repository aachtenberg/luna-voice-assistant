# Luna Voice Assistant

Self-hosted voice assistant replacing Alexa with local/cloud LLMs, smart home control, and privacy-first design.

## Features

- **Wake word detection** - Custom "Hey Luna" model via OpenWakeWord
- **Speech-to-text** - faster-whisper (runs on server)
- **LLM backends** - Anthropic Claude, Ollama (local), or Groq
- **Text-to-speech** - Piper TTS (local, fast)
- **Smart home control** - Kasa switches, WiZ bulbs
- **Tools** - Web search (SearXNG), weather (Open-Meteo), sensor data (TimescaleDB), timers
- **Follow-up conversations** - Listens after asking questions without wake word
- **Observability** - Prometheus metrics, structured JSON logging

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Raspberry Pi (Voice Node)                    │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│  │ Wake Word│ → │ Record   │ → │ Whisper  │ → │ Brain    │     │
│  │ Detector │   │ Audio    │   │ (remote) │   │ Service  │     │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘     │
│                                                    ↓            │
│  ┌──────────┐   ┌──────────┐                 ┌──────────┐      │
│  │ Speaker  │ ← │ Piper    │ ←───────────────│ LLM      │      │
│  │ Output   │   │ TTS      │                 │ +Tools   │      │
│  └──────────┘   └──────────┘                 └──────────┘      │
└─────────────────────────────────────────────────────────────────┘
                                                    ↓
┌─────────────────────────────────────────────────────────────────┐
│                     Server (Compute Node)                        │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                    │
│  │ Whisper  │   │ Ollama   │   │ SearXNG  │                    │
│  │ STT      │   │ LLM      │   │ Search   │                    │
│  └──────────┘   └──────────┘   └──────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

## Hardware Used (Reference Build)

### Voice Node
| Component | Model | Notes |
|-----------|-------|-------|
| SBC | Raspberry Pi 5 (8GB) | Pi 4 works, Pi 3 is slow |
| Audio | Anker PowerConf S330 | USB speakerphone with AEC, works great |
| Storage | 32GB+ SD card | |

### Compute Node (Optional - for local LLM)
| Component | Model | Notes |
|-----------|-------|-------|
| GPU | AMD Radeon RX 7900 XTX | 24GB VRAM; NVIDIA/AMD/Intel Arc all work |
| CPU | AMD Ryzen 7 7800X3D | |
| RAM | 32GB DDR5 | |
| OS | Windows 11 + WSL2 | Or native Linux |

**GPU Recommendations:**
- **NVIDIA**: Best compatibility with Ollama/CUDA. RTX 3060 12GB+ works well.
- **AMD**: Works with ROCm. 7900 XTX (24GB) handles large models easily.
- **Intel Arc**: Experimental support in Ollama.
- **CPU-only**: Possible but slow. 32GB+ RAM recommended for 7B models.

### LLM & Speech Models
| Service | Model | Where it runs |
|---------|-------|---------------|
| LLM (cloud) | Claude 3.5 Haiku | Anthropic API |
| LLM (local) | Qwen 2.5 14B | Ollama on server |
| STT | faster-whisper large-v3 | Server (CUDA) |
| TTS | Piper en_US-hfc_female-medium | Pi (local) |
| Wake word | OpenWakeWord (custom) | Pi (local) |

### Supporting Services
| Service | Purpose | Where it runs |
|---------|---------|---------------|
| SearXNG | Web search | Docker on server |
| TimescaleDB | Sensor data | Docker or k3s on server |
| Prometheus | System metrics | Docker on server |
| MQTT (Mosquitto) | Timer notifications | Docker on server |

### Smart Home Devices
| Device | Model | Protocol |
|--------|-------|----------|
| Kitchen switch | TP-Link Kasa HS200 | Kasa (works) |
| Patio switch | TP-Link Kasa HS200 | Kasa (works) |
| Living room bulbs | WiZ A19 (x2) | WiZ (works) |

**Note:** Tuya-based devices (Geeni, Amazon Basics) require cloud key extraction and are not straightforward to set up.

## Prerequisites

### Hardware
- **Raspberry Pi 4/5** (Pi 3 works but slower) - runs voice service
- **USB speakerphone** (e.g., Anker PowerConf S330) or separate mic + speaker
- **Server** (optional) - for local LLM and Whisper if not using cloud APIs

### Software Dependencies

**On the Pi:**
```bash
# System packages
sudo apt install python3-venv python3-dev portaudio19-dev pipewire pipewire-audio wireplumber

# Piper TTS - download binary
mkdir -p ~/piper
wget https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_arm64.tar.gz
tar -xzf piper_arm64.tar.gz -C ~/piper

# Piper voice model
mkdir -p ~/piper-voices
wget -O ~/piper-voices/en_US-hfc_female-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/hfc_female/medium/en_US-hfc_female-medium.onnx
wget -O ~/piper-voices/en_US-hfc_female-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/hfc_female/medium/en_US-hfc_female-medium.onnx.json
```

**On the server (if using local LLM/Whisper):**
```bash
# Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:14b  # or your preferred model

# faster-whisper-compatible transcription server
# Luna prefers an OpenAI-style endpoint at /v1/audio/transcriptions
# and falls back to /transcribe if needed.
```

### External Services (choose LLM provider)

| Provider | Requirement | Cost |
|----------|-------------|------|
| Anthropic Claude | API key | ~$0.25/1M tokens |
| Ollama (local) | Server with GPU | Free |
| Groq | API key | Free tier available |

## Installation

### 1. Clone and setup

```bash
git clone https://github.com/aachtenberg/luna-voice-assistant.git
cd luna-voice-assistant

# Brain service
cd brain
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Voice service
cd ../voice
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

Start from the committed examples:

```bash
cp brain/.env.example brain/.env
cp voice/.env.example voice/.env
```

**brain/.env:**
```bash
# LLM Provider: single (ollama, anthropic, groq) or fallback chain (comma-separated)
LLM_PROVIDER=ollama,groq,anthropic

# Anthropic (if using Claude)
ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_MODEL=claude-3-5-haiku-latest

# Ollama (if using local)
OLLAMA_URL=http://your-server:11434
# Auto-select currently loaded model on Ollama server
OLLAMA_AUTO_MODEL=true
# Fallback if no model is currently loaded
OLLAMA_MODEL=qwen2.5:14b
# Refresh interval for active-model detection
OLLAMA_MODEL_REFRESH_SECONDS=5

# Groq (if using Groq)
GROQ_API_KEY=gsk_xxx
GROQ_MODEL=llama-3.1-70b-versatile

# Services
MQTT_BROKER=192.168.x.x
MQTT_PORT=1883
TIMESCALEDB_HOST=192.168.x.x
TIMESCALEDB_PORT=5433
TIMESCALEDB_DATABASE=sensors
TIMESCALEDB_USER=telegraf
TIMESCALEDB_PASSWORD=replace-me
PROMETHEUS_URL=http://192.168.x.x:9090
SEARXNG_URL=http://192.168.x.x:8089

# Optional location override for weather
LOCATION_CITY=Pembroke
LOCATION_REGION=Ontario
LOCATION_COUNTRY=Canada
LOCATION_TIMEZONE=Eastern Time
LOCATION_LAT=45.8167
LOCATION_LON=-77.1167
```

**voice/.env:**
```bash
BRAIN_URL=http://your-brain-host:8000
WHISPER_URL=http://your-server:8000
PIPER_PATH=/home/youruser/piper/piper
PIPER_MODEL=/home/youruser/piper-voices/en_US-hfc_female-medium.onnx
WAKEWORD_THRESHOLD=0.5
# VAD threshold for OpenWakeWord (0.0 = disabled, recommended for home use)
VAD_THRESHOLD=0.0
STREAMING_STT_ENABLED=true
BARGE_IN_ENABLED=true

# MQTT for timer notifications
MQTT_BROKER=192.168.x.x
MQTT_PORT=1883

# Logging format: text or json
LOG_FORMAT=text
```

### 3. Configure smart devices

Edit `brain/tools/kasa.py` with your device IPs. Right now the Kasa and WiZ device mappings are code-based, not environment-driven:
```python
KASA_DEVICES = {
    "kitchen": "192.168.x.x",
    "patio": "192.168.x.x",
}

WIZ_DEVICES = {
    "living room": ["192.168.x.x", "192.168.x.x"],  # Multiple bulbs as group
}
```

### 4. Run services

**Option A: Docker (brain only)**
```bash
docker compose up -d brain
cd voice && source venv/bin/activate && python main.py
```

**Option B: Manual**
```bash
# Terminal 1 - Brain
cd brain && source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2 - Voice
cd voice && source venv/bin/activate
python main.py
```

**Option C: k3s (recommended for homelab cluster)**

`brain/` is deployed to k3s, while `voice/` runs bare metal on Raspberry Pi.
Kubernetes manifests/source of truth: https://github.com/aachtenberg/homelab-infra

Quick deploy flow:
```bash
# docker is not available on cluster nodes — use nerdctl with k8s.io namespace
sudo nerdctl --namespace k8s.io build --no-cache -t homelab-app-brain:latest ./brain/

# Import into k3s containerd store (nerdctl and k3s use separate stores)
sudo nerdctl --namespace k8s.io save homelab-app-brain:latest | sudo k3s ctr images import -

# Restart deployment
kubectl rollout restart deploy/luna-brain -n apps
kubectl rollout status deploy/luna-brain -n apps --timeout=60s
```

Preferred: keep deployment state in `homelab-infra` manifests; use manual patching only for hotfixes.

Full guide: `docs/k3s-deploy.md`

## Usage

Say "Hey Luna" followed by your command:

- "Hey Luna, turn on the kitchen light"
- "Hey Luna, set living room to 50%"
- "Hey Luna, what's the temperature in the garage?"
- "Hey Luna, set a timer for 5 minutes"
- "Hey Luna, what's the weather?"

### Follow-up Conversations
When Luna asks a question (response ends with "?"), she listens for your answer without needing the wake word again.

## Gotchas & Troubleshooting

### Audio Issues

**No audio input detected:**
```bash
# Check PipeWire is running
systemctl --user status pipewire

# List audio devices
pactl list sources short

# Set default source
pactl set-default-source <device-name>
```

**Wake word triggers on TTS playback:**
- The code has barge-in detection with cooldown logic; tune via `COOLDOWN_SECONDS` and `WAKEWORD_THRESHOLD` env vars
- Using a speakerphone with AEC (acoustic echo cancellation) helps

### Smart Home

**Kasa devices not responding:**
```bash
# Test from a shell with network access to the device
cd brain && source venv/bin/activate && python3 -c "
from kasa import Discover
import asyncio
async def test():
    dev = await Discover.discover_single('192.168.x.x', timeout=5)
    print(dev.alias, dev.model)
asyncio.run(test())
"
```

**WiZ bulbs timeout:**
- WiZ bulbs use UDP port 38899
- Ensure firewall allows UDP traffic on local network
- Bulbs must be on same subnet as Pi

### LLM Issues

**Ollama tool calling not working:**
- Ollama's tool calling can be inconsistent with some models
- Try `qwen2.5:14b` or switch to Anthropic Claude
- Claude handles tool calling more reliably

**Slow responses:**
- Local LLMs on CPU are slow - use GPU or cloud API
- Whisper transcription adds latency - consider cloud STT

### Timer Notifications

**Timers not announcing:**
- Ensure MQTT broker is running and accessible
- Check voice service is subscribed: look for `[MQTT] Subscribed to voice-assistant/timer` in logs
- Brain persists timers to `brain/data/timers.json` and restores active timers on startup
- Voice still needs MQTT connectivity to receive and announce timer completions

## Metrics & Observability

**Prometheus endpoints:**
- Brain: `http://<brain-host>:8000/metrics`
- Voice: `http://<voice-host>:8001/metrics`

**Key metrics:**
- `brain_request_duration_seconds` - LLM response time
- `brain_tool_calls_total{tool_name}` - Tool usage
- `voice_wakeword_detections_total` - Wake word triggers
- `voice_conversation_duration_seconds` - End-to-end latency
- `voice_listening` - Current voice loop state (1=listening, 0=processing)

**Structured logging:**
- Set `LOG_FORMAT=json` for Loki-compatible JSON logs
- Default is plain text

## Smart Device Compatibility

| Device Type | Protocol | Supported |
|------------|----------|-----------|
| TP-Link Kasa switches | Kasa | ✅ |
| TP-Link Kasa plugs | Kasa | ✅ |
| WiZ bulbs | WiZ | ✅ |
| Tuya/Geeni/Amazon Basics | Tuya | ❌ (needs cloud key) |

To add Tuya devices, you need to extract local keys via Tuya IoT platform - not straightforward.

## Project Structure

```
├── brain/                    # FastAPI LLM service
│   ├── main.py              # API endpoints
│   ├── llm/                 # LLM provider implementations
│   │   ├── anthropic.py     # Claude
│   │   ├── ollama.py        # Local Ollama
│   │   ├── groq.py          # Groq cloud
│   │   └── fallback.py      # FallbackProvider chain
│   ├── tools/               # Tool implementations
│   │   ├── kasa.py          # Smart lights (Kasa + WiZ)
│   │   ├── timers.py        # Timer functionality
│   │   ├── web_search.py    # SearXNG
│   │   ├── timescaledb.py   # Sensor data
│   │   └── weather.py       # Forecast and current weather
│   └── Dockerfile
├── voice/                    # Voice interface
│   ├── main.py              # Main loop
│   ├── wakeword.py          # OpenWakeWord detection
│   ├── audio.py             # Recording
│   ├── stt.py               # Whisper client
│   ├── tts.py               # Piper TTS
│   ├── luna-voice.service   # Systemd unit for bare-metal runtime
│   └── assets/              # Wake word models
├── docs/
│   └── k3s-deploy.md        # Build/deploy runbook for k3s
└── docker-compose.yml
```

### Running as a Systemd Service (Bare Metal)

To run the voice service resiliently on bare metal (e.g., Raspberry Pi), use the provided systemd service file.

Before installing it, adjust `voice/luna-voice.service` for your environment:
- `User=` must match the Linux user that owns the PipeWire session
- `WorkingDirectory=` and `ExecStart=` must match your checkout path
- `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS`, and `PULSE_SERVER` must match that user's runtime directory

1. Copy the service file:
   ```
   sudo cp voice/luna-voice.service /etc/systemd/system/
   ```

2. Reload systemd:
   ```
   sudo systemctl daemon-reload
   ```

3. Enable and start the service:
   ```
   sudo systemctl enable --now luna-voice.service
   ```

4. Check status:
   ```
   sudo systemctl status luna-voice.service
   ```

5. If the service user does not stay logged in, enable lingering so `/run/user/<uid>` stays available after reboot/logout:
   ```
   sudo loginctl enable-linger <user>
   ```

The service will automatically restart on failures, wait for the network to be online, load environment variables from `voice/.env` via `EnvironmentFile=` when that file exists, and export the user PipeWire runtime variables needed by `pw-play` and `wpctl`.

To follow logs:
```
sudo journalctl -u luna-voice.service -f
```

# License

MIT
