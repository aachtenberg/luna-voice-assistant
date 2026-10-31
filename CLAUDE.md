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
│   ├── probes.py            # Health probes that spend no credits
│   ├── tracing.py           # Opt-in OpenTelemetry spans
│   ├── llm/                 # Provider implementations + fallback chain
│   └── tools/               # Tool implementations
│       ├── web_search.py    # SearXNG
│       ├── prometheus.py    # PromQL queries
│       ├── timescaledb.py   # Sensor data SQL queries
│       ├── mqtt.py          # MQTT publish
│       ├── timers.py        # Persistent timers
│       ├── kasa.py          # Kasa switch + bulb control
│       └── weather.py       # Open-Meteo weather queries
├── voice/                    # Voice assistant (runs on Pi)
│   ├── main.py              # Main loop
│   ├── audio.py             # Mic recording with sounddevice
│   ├── wakeword.py          # OpenWakeWord detection
│   ├── stt.py               # Whisper transcription
│   ├── tts.py               # Piper TTS + pw-play
│   ├── brain_client.py      # HTTP client to brain service
│   ├── metrics_server.py    # Prometheus /metrics endpoint
│   ├── tracing.py           # Opt-in OpenTelemetry spans
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

The old bare-metal TimescaleDB (192.168.0.146:5433) is retired; sensor data
lives in the k3s `timescaledb` StatefulSet (`timescaledb.data.svc.cluster.local:5432`,
db `sensors`, user `telegraf`).

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

**GitOps — just push to `main`.** Deployment is fully automated; there is no
manual image build and no node access.

```bash
git add brain/ && git commit -m "..." && git push   # to main
```

Pipeline (on any push touching `brain/**`):
1. `.github/workflows/build-luna-brain.yml` builds a **linux/arm64** image (the
   pod is pinned to raspberrypi3) via QEMU and pushes
   `ghcr.io/aachtenberg/luna-brain:main` + immutable `:main-<sha7>` to GHCR.
2. Its `bump-deploy-repo` job commits the new tag into the private deploy repo
   `luna-voice-assistant-deploy` (auth via the `LUNA_DEPLOY_PAT` repo secret).
3. ArgoCD's standalone `luna-brain` Application syncs the bump and rolls the pod.

Watch it land:
```bash
gh run watch -R aachtenberg/luna-voice-assistant   # the build
kubectl get application luna-brain -n argocd -w     # the rollout
```

**Notes**:
- The deploy manifests (topology-bearing) live in the private repo, NOT here.
- The cluster pulls from GHCR via the `ghcr-pull-secret` already in the `apps` namespace.
- Don't hand-edit live resources — ArgoCD `selfHeal` reverts them; change git.
- Legacy: the old hand-built `homelab-app-brain` + `imagePullPolicy: Never` /
  `nerdctl ... | k3s ctr images import` flow is **retired**.

## Switching the LLM at runtime

The brain builds its provider once at startup from env vars, but exposes a web
UI at `GET /admin` (served on NodePort `30900` → e.g.
http://192.168.0.111:30900/admin) and a JSON `/admin/provider` API to switch
provider/model **live** (no redeploy):

```bash
curl http://<brain>:8000/admin/provider                 # GET  — current config + active chain
curl -X POST http://<brain>:8000/admin/provider \       # POST — partial update (only sent fields change)
  -H "Content-Type: application/json" -d '{"provider":"groq"}'
curl -X DELETE http://<brain>:8000/admin/provider        # revert to env defaults
```

The override persists to `LLM_OVERRIDE_PATH` (default `/app/data/llm_override.json`,
on the mounted data volume) so it survives restarts. API keys are never settable
this way. On the cluster, the deploy repo's `luna-llm` CLI wraps these calls.

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
- Runtime LLM switching via `/admin/provider` (persisted override, survives restarts)
- GitOps CI/CD: push → GH Actions arm64 build → GHCR → deploy-repo bump → ArgoCD
- Voice service with OpenWakeWord ("hey luna"), Whisper, Piper TTS
- Audio handling: Anker S330 USB speakerphone via PipeWire
- Barge-in support (interrupt TTS with wake word)
- Whisper hallucination filtering
- TimescaleDB sensor queries working
- Systemd service for resilient bare-metal voice runtime
- Structured JSON logging (Loki-compatible)
- OpenTelemetry tracing, voice to brain to LLM to TTS, into Tempo

## Tracing

One trace per conversation in Tempo, read through Grafana, from the wake word to
the last sentence played:

```
conversation                           luna-voice; luna.outcome, luna.wake.score
├─ tts.speak                           the "Yes?"
├─ audio.record
│  └─ stt.warmup
├─ stt.transcribe                      luna.stt.filtered = hallucination dropped
└─ answer                              luna.time_to_first_audio_ms, luna.barged_in
   ├─ brain.ask_stream ─ traceparent ─► POST /ask/stream     luna-brain
   │                                    ├─ chat <model>      tokens, luna.ollama.load_ms
   │                                    ├─ execute_tool <tool>
   │                                    └─ chat <model>      luna.time_to_first_token_ms
   └─ tts.synthesize, tts.play         one pair per sentence
```

Useful TraceQL: `{ name = "conversation" && span.luna.outcome != "answered" }`,
`{ span.luna.ollama.load_ms > 1000 }` (cold model), `{ span.gen_ai.tool.name != nil && status = error }`.

**On/off**: `OTEL_EXPORTER_OTLP_ENDPOINT` set means on, unset means off and the SDK
is never imported. Direct OTLP/HTTP to Tempo on 4318, no collector. The brain uses
Tempo's cluster DNS name; voice uses its ClusterIP, as host DNS can't resolve it.

**Rules** (same as cfoperator, whose attribute names these match):
- **Shapes, not text.** Models, tokens, tool names, durations, lengths. Never a
  transcript, prompt, response, tool argument or tool output; exceptions record
  the class only. The text stays in the logs, and every log line inside a trace
  ends in `trace_id=<id>`, so a trace still leads to it.
- **Only `tracing.py` names `opentelemetry`.**
- **Not `span()` across a `yield`.** Use `detached_span()`: Starlette resumes sync
  generators on pool threads, so a current span would detach in the wrong context.
- **A new thread starts outside the trace.** To join it, run the target under
  `contextvars.copy_context().run`, as `speak_streamed` does.
- **Tools report failure as return strings**, so call `tracing.mark_error()`
  beside them or the span shows success.

FastAPI (>=0.162) makes the server span itself once a provider exists; `main.py`
only turns off its per-operation spans and excludes `/health` and `/metrics`.
A barge-in hangs up on the brain, so its server span reads ERROR
`error.type=ConnectionError`. That is the disconnect, not a fault; the voice side's
`luna.outcome=barged_in` says which it was.

Metrics stay on Prometheus and logs on Loki. Tempo derives span metrics into
Prometheus as `traces_spanmetrics_*`.

## Health probes

`/health` only says the process is up. `brain/probes.py` asks whether Luna can
still do her job, and spends no credits doing it:

```bash
curl -X POST http://<brain>:8000/admin/probe   # run every check once, now
```

| Check | What it does | What it catches | What it misses |
|-------|--------------|-----------------|----------------|
| `groq` | Lists models, no tokens | Bad key, outage, retired model | Spent quota |
| `ollama` | Lists installed models, nothing loaded | Server down, model not pulled | A model that won't run |
| `search` | One SearXNG query | Empty results, engines blocked, SearXNG down | |

Anthropic isn't checked: it isn't funded, so it would only ever fail. Results go to
`brain_probe_success`, `brain_probe_duration_seconds` and
`brain_probe_last_run_timestamp_seconds`, labelled by `check`, and failures to the log.

**No timer yet, on purpose.** `PROBE_INTERVAL_SECONDS` defaults to 0: no thread, no
calls, no metrics. It stays 0 until a local model does all the inference. Then, in
the deploy repo, set:

- `PROBE_INTERVAL_SECONDS=900`.
- `PROBE_OLLAMA_HELLO=true`, which adds a real chat a few tokens long to `ollama`,
  catching a model that won't run. Only on a GPU Luna doesn't share: the hello loads
  the model and could evict someone else's.
- `PROBE_SEARCH_INTERVAL_SECONDS` stays at 3600. Each query spends search engine quota.

**Rules**: never send a prompt to a paid provider from a probe, and never go through
`/ask`, which writes to the one history every conversation shares.

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
- OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_RESOURCE_ATTRIBUTES (see Tracing)
- PROBE_INTERVAL_SECONDS, PROBE_SEARCH_INTERVAL_SECONDS, PROBE_OLLAMA_HELLO (see Health probes)
- Secrets via k8s Secret `luna-brain-secrets`

These env vars are **startup defaults**. The provider/model routing fields
(`LLM_PROVIDER`, `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_AUTO_MODEL`,
`GROQ_MODEL`, `ANTHROPIC_MODEL`) can be overridden live via `/admin/provider`;
the override persists to `LLM_OVERRIDE_PATH` (default
`/app/data/llm_override.json`) and is re-applied at startup.

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
BARGE_IN_DEVICE=luna_barge
OTEL_EXPORTER_OTLP_ENDPOINT=http://<tempo-clusterip>:4318
```

## Barge-in and Stop

- **Barge-in mic**: `BARGE_IN_DEVICE=luna_barge` is the second USB mic (USB PnP)
  run through PipeWire WebRTC echo cancellation, with the speaker's monitor as
  the reference. Raw, that mic hears Luna 5–25× louder than the user, so the
  wake word never scores. Set it up on the voice host with
  `voice/setup-echo-cancel.sh` (writes `~/.config/pipewire/pipewire.conf.d/luna-echo-cancel.conf`
  + `~/.asoundrc`, lowers the mic gain, turns its AGC off). Each
  `Barge-in monitor: ... max wake score` log line shows how close detection came.
- **Stop without the wake word**: the kiosk's Stop button, `curl -X POST http://<voice-host>:8001/stop`,
  or any MQTT message on `voice-assistant/stop` cuts TTS and returns to wake-word listening.

## Location Context

Property in Pembroke, Ontario, Canada (Eastern Time). Weather queries use this location.
