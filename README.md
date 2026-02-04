# Luna Voice Assistant

Self-hosted voice assistant replacing Alexa with local/cloud LLMs, smart home control, and privacy-first design.

## Features

- **Wake word detection** - Custom "Hey Luna" model via OpenWakeWord
- **Speech-to-text** - faster-whisper (runs on server)
- **LLM backends** - Anthropic Claude, Ollama (local), or Groq
- **Text-to-speech** - Piper TTS (local, fast)
- **Smart home control** - Kasa switches, WiZ bulbs
- **Tools** - Web search (SearXNG), temperature sensors (InfluxDB), timers
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
| TTS | Piper en_US-lessac-medium | Pi (local) |
| Wake word | OpenWakeWord (custom) | Pi (local) |

### Supporting Services
| Service | Purpose | Where it runs |
|---------|---------|---------------|
| SearXNG | Web search | Docker on server |
| InfluxDB 3 | Temperature sensors | Docker on server |
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
sudo apt install python3-venv python3-dev portaudio19-dev pipewire pipewire-audio

# Piper TTS - download binary
wget https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_arm64.tar.gz
tar -xzf piper_arm64.tar.gz -C ~/piper

# Piper voice model
mkdir -p ~/piper-voices
wget -O ~/piper-voices/en_US-lessac-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget -O ~/piper-voices/en_US-lessac-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
```

**On the server (if using local LLM/Whisper):**
```bash
# Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.1:8b  # or your preferred model

# faster-whisper server
pip install faster-whisper
# Run as service on port 8090
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

**brain/.env:**
```bash
# LLM Provider: ollama, anthropic, or groq
LLM_PROVIDER=anthropic

# Anthropic (if using Claude)
ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_MODEL=claude-3-5-haiku-latest

# Ollama (if using local)
OLLAMA_URL=http://your-server:11434
OLLAMA_MODEL=llama3.1:8b

# Groq (if using Groq)
GROQ_API_KEY=gsk_xxx
GROQ_MODEL=llama-3.1-70b-versatile

# Services
MQTT_BROKER=192.168.x.x
MQTT_PORT=1883
INFLUXDB_URL=http://192.168.x.x:8181
INFLUXDB_TOKEN=your-token
INFLUXDB_DATABASE=temperature_data
PROMETHEUS_URL=http://192.168.x.x:9090
SEARXNG_URL=http://192.168.x.x:8089
```

**voice/.env:**
```bash
BRAIN_URL=http://localhost:8000
WHISPER_URL=http://your-server:8090
PIPER_PATH=/home/youruser/piper/piper
PIPER_MODEL=/home/youruser/piper-voices/en_US-lessac-medium.onnx
WAKEWORD_THRESHOLD=0.7

# MQTT for timer notifications
MQTT_BROKER=192.168.x.x
MQTT_PORT=1883
```

### 3. Configure smart devices

Edit `brain/tools/kasa.py` with your device IPs:
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
- The code has cooldown logic but may need tuning
- Adjust `COOLDOWN_CHUNKS` in `voice/main.py`
- Using a speakerphone with AEC (acoustic echo cancellation) helps

### Smart Home

**Kasa devices not responding:**
```bash
# Test from brain container
docker exec luna-brain python3 -c "
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
- Timer state is in-memory only - restarts lose active timers

## Metrics & Observability

**Prometheus endpoints:**
- Brain: `http://pi-ip:8000/metrics`
- Voice: `http://pi-ip:8001/metrics`

**Key metrics:**
- `brain_request_duration_seconds` - LLM response time
- `brain_tool_calls_total{tool_name}` - Tool usage
- `voice_wakeword_detections_total` - Wake word triggers
- `voice_conversation_duration_seconds` - End-to-end latency

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
│   │   └── groq.py          # Groq cloud
│   ├── tools/               # Tool implementations
│   │   ├── kasa.py          # Smart lights (Kasa + WiZ)
│   │   ├── timers.py        # Timer functionality
│   │   ├── web_search.py    # SearXNG
│   │   └── influxdb.py      # Temperature sensors
│   └── Dockerfile
├── voice/                    # Voice interface
│   ├── main.py              # Main loop
│   ├── wakeword.py          # OpenWakeWord detection
│   ├── audio.py             # Recording
│   ├── stt.py               # Whisper client
│   ├── tts.py               # Piper TTS
│   └── assets/              # Wake word models
└── docker-compose.yml
```

## License

MIT
