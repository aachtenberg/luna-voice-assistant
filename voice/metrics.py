"""Prometheus metrics for voice service."""

import time
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Wake word metrics
WAKEWORD_DETECTIONS = Counter(
    'voice_wakeword_detections_total',
    'Total wake word detections'
)

WAKEWORD_FALSE_TRIGGERS = Counter(
    'voice_wakeword_false_triggers_total',
    'Wake word false triggers (no speech followed)'
)

# Audio metrics
RECORDING_DURATION = Histogram(
    'voice_recording_duration_seconds',
    'Recording duration in seconds',
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
)

AUDIO_AMPLITUDE = Histogram(
    'voice_audio_amplitude',
    'Audio amplitude levels',
    buckets=[10, 30, 50, 100, 200, 500, 1000, 5000]
)

# STT metrics
STT_REQUESTS = Counter(
    'voice_stt_requests_total',
    'Total STT requests',
    ['status']
)

STT_DURATION = Histogram(
    'voice_stt_duration_seconds',
    'STT processing time',
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

# TTS metrics
TTS_REQUESTS = Counter(
    'voice_tts_requests_total',
    'Total TTS requests'
)

TTS_DURATION = Histogram(
    'voice_tts_duration_seconds',
    'TTS generation + playback time',
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# Brain client metrics
BRAIN_REQUESTS = Counter(
    'voice_brain_requests_total',
    'Requests to brain service',
    ['status']
)

BRAIN_DURATION = Histogram(
    'voice_brain_duration_seconds',
    'Brain service response time',
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
)

# Conversation metrics
CONVERSATIONS_TOTAL = Counter(
    'voice_conversations_total',
    'Total voice conversations completed'
)

CONVERSATION_DURATION = Histogram(
    'voice_conversation_duration_seconds',
    'Total conversation duration (wake word to response complete)',
    buckets=[1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0]
)

# Current state
LISTENING_STATE = Gauge(
    'voice_listening',
    'Voice service listening state (1=listening, 0=processing)'
)


def get_metrics():
    """Return metrics in Prometheus format."""
    return generate_latest()


def get_content_type():
    """Return Prometheus content type."""
    return CONTENT_TYPE_LATEST
