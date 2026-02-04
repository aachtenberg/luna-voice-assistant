# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Luna** - Self-hosted voice assistant replacing Alexa with local LLMs, web search, and home automation integration.

## Architecture

**Two-node system:**
- **Raspberry Pi 3**: Voice endpoint (wake word detection, audio capture, Piper TTS playback)
- **5080 Server (WSL2)**: Compute backend (Ollama LLM, faster-whisper STT, SearXNG search)

**Data flow**: Wake word → Audio capture → Whisper transcription → Brain/LLM → TTS response → Playback

## Project Structure

```
homelab-app/
├── brain/                    # FastAPI service (runs on Pi, calls remote services)
│   ├── main.py              # /ask endpoint
│   ├── ollama_client.py     # LLM + tool calling loop
│   ├── prompts.py           # System prompt + tool definitions
│   ├── config.py            # Environment-based configuration
│   └── tools/               # Tool implementations
│       ├── web_search.py    # SearXNG
│       ├── influxdb.py      # InfluxDB 3 SQL queries
│       ├── prometheus.py    # PromQL queries
│       └── mqtt.py          # MQTT publish
├── voice/                    # Voice assistant (runs on Pi)
│   ├── main.py              # Main loop
│   ├── audio.py             # Mic recording with sounddevice
│   ├── wakeword.py          # OpenWakeWord detection
│   ├── stt.py               # Whisper transcription
│   ├── tts.py               # Piper TTS + pw-play
│   └── brain_client.py      # HTTP client to brain service
└── docs/
    └── broker-topics-known.txt
```

## Services & Endpoints

| Service | Host | Port | Purpose |
|---------|------|------|---------|
| Brain API | Pi | 8000 | FastAPI, routes to LLM |
| Piper TTS | Pi | - | Local binary ~/piper/piper |
| faster-whisper | WSL2 | 8090 | Speech-to-text |
| Ollama | WSL2 | 11434 | LLM (qwen2.5:14b) |
| SearXNG | WSL2 | 8089 | Web search |
| InfluxDB 3 | Docker | 8181 | Sensor data (SQL API) |
| Prometheus | Docker | 9090 | System metrics |
| MQTT | Docker | 1883 | Home automation |

## Commands

```bash
# Start brain service
cd brain && source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000

# Start voice assistant
cd voice && source venv/bin/activate && python main.py

# Test brain directly
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"text": "What time is it?"}'

# Test InfluxDB query
curl -s -X POST 'http://192.168.0.167:8181/api/v3/query_sql' \
  -H 'Authorization: Bearer $INFLUXDB_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"db": "temperature_data", "q": "SELECT * FROM esp_temperature LIMIT 5"}'
```

## InfluxDB Schema

**Database**: `temperature_data`
**Table**: `esp_temperature`
**Columns**: device, celsius, fahrenheit, humidity (optional), time
**Devices**: Spa, Main-Cottage, Big-Garage, Small-Garage, Pump-House, Sauna, Shack-ICF, Weather-Station-Main

## Current Status

### ✅ Completed
- Brain service with Ollama tool calling (qwen2.5:14b)
- Tools: web_search, query_influxdb, query_prometheus, mqtt_publish
- Voice service with OpenWakeWord, Whisper, Piper
- Audio handling: USB mic + Bluetooth speaker via PipeWire
- Time injection in system prompt
- Whisper hallucination filtering
- InfluxDB 3 SQL queries working

### 🔄 In Progress / Issues
- **Wake word self-triggering**: Still occasionally triggers on ambient noise after TTS
- **Recording timing**: Cooldown/flush balance - too aggressive loses speech, too light causes loops

### 📋 Next Steps
1. **Custom wake word**: Train "Yo Luna" model in Colab, deploy to voice/models/
2. **Barge-in support**: Revisit when using separate USB mic + speaker (not Bluetooth earbuds)
3. **Conversation context**: Add multi-turn memory to brain service
4. **Systemd services**: Create service files for brain and voice
5. **Error handling**: Better recovery from network failures
6. **Logging**: Add structured logging for debugging

## Configuration

Both services use `.env` files (not committed, see `.env.example`):

**brain/.env**:
```
OLLAMA_URL=http://192.168.0.198:11434
OLLAMA_MODEL=qwen2.5:14b
INFLUXDB_URL=http://192.168.0.167:8181
INFLUXDB_TOKEN=<token>
INFLUXDB_DATABASE=temperature_data
...
```

**voice/.env**:
```
BRAIN_URL=http://localhost:8000
WHISPER_URL=http://192.168.0.198:8090
PIPER_PATH=/home/aachten/piper/piper
PIPER_MODEL=/home/aachten/piper-voices/en_US-lessac-medium.onnx
WAKEWORD_THRESHOLD=0.8
```

## Location Context

Property in Pembroke, Ontario, Canada (Eastern Time). Weather queries use this location.
