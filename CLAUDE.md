# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Self-hosted voice assistant replacing Alexa with local LLMs, web search, and home automation integration.

## Architecture

**Two-node system:**
- **Raspberry Pi 3**: Voice endpoint (wake word detection, audio capture, Piper TTS playback)
- **5080 Server (WSL2)**: Compute backend (Ollama LLM, faster-whisper STT, SearXNG search, brain service)

**Data flow**: Wake word → Audio capture → Stream to server → Whisper transcription → LLM processing → TTS response → Playback

## Services

| Service | Host | Port | Purpose |
|---------|------|------|---------|
| Piper TTS | Pi | - | Text-to-speech (local binary at ~/piper/piper) |
| faster-whisper | WSL2 | 8090 | Speech-to-text (GPU accelerated) |
| Ollama | WSL2 | 11434 | LLM inference |
| SearXNG | WSL2 | 8089 | Web search |

## Commands

```bash
# Piper TTS (local binary on Pi)
echo "Hello" | ~/piper/piper --model ~/piper-voices/en_US-lessac-medium.onnx --output_file test.wav

# Test faster-whisper
curl -X POST "http://localhost:8090/v1/audio/transcriptions" -F "file=@test.m4a" -F "model=medium"

# Test SearXNG
curl "http://localhost:8089/search?q=test&format=json"
```

## Current State

- **Phase 1 (Infrastructure)**: Complete - SearXNG, faster-whisper, Piper all running
- **Phase 2 (Brain Service)**: In progress - needs Ollama/MQTT/InfluxDB endpoints configured
- **Phase 3 (Pi Hardware)**: Pending - needs USB speakerphone or ReSpeaker HAT

## Infrastructure Endpoints

| Service | URL |
|---------|-----|
| Ollama | http://192.168.0.198:11434 |
| MQTT Broker | 192.168.0.167:1883 |
| InfluxDB | http://192.168.0.167:8181 |
| Prometheus | http://192.168.0.167:9090 |
| Loki | http://192.168.0.167:3100 |
| SearXNG | http://localhost:8089 |
| faster-whisper | http://localhost:8090 |

## Planned Integrations

The brain service will connect to: MQTT broker, InfluxDB (sensors), Prometheus (metrics). LLM will have tools for web search and sandboxed Python code execution against home infrastructure.
