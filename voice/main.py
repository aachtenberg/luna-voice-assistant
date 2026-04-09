#!/usr/bin/env python3
"""Voice assistant main loop."""

import os
import signal
import sys
import time
import json
import threading
import paho.mqtt.client as mqtt
from audio import AudioRecorder
from wakeword import WakeWordDetector
from stt import transcribe, transcribe_streaming
from tts import speak, speak_streamed, stop_speaking, announce_timer, start_thinking_loop, stop_thinking_loop
from brain_client import ask, ask_stream
from config import (
    MQTT_BROKER, MQTT_PORT, TIMER_TOPIC, STREAMING_STT_ENABLED,
    COOLDOWN_SECONDS, CHUNK_DURATION, POST_TTS_PAUSE, POST_EMPTY_PAUSE,
    AUDIO_SETTLE_PAUSE, MAX_RECORD_SECONDS, FOLLOWUP_MAX_SECONDS,
    MIN_SPEECH_BYTES, BARGE_IN_ENABLED
)
from logging_config import setup_logging
from metrics_server import start_metrics_server
from metrics import (
    WAKEWORD_DETECTIONS, WAKEWORD_FALSE_TRIGGERS,
    RECORDING_DURATION, STT_REQUESTS, STT_DURATION,
    TTS_REQUESTS, BRAIN_REQUESTS, BRAIN_DURATION,
    CONVERSATIONS_TOTAL, CONVERSATION_DURATION, LISTENING_STATE,
    STREAM_DEAD_RECOVERIES
)

# Setup structured logging (JSON for Loki, plain text if LOG_FORMAT=text)
log = setup_logging(json_output=os.getenv("LOG_FORMAT", "text") != "text")

# Global flag for shutdown
running = True

# Cooldown chunks to ignore after TTS (prevents self-triggering from echo)
COOLDOWN_CHUNKS = int(COOLDOWN_SECONDS / CHUNK_DURATION)

# Queue for timer announcements
timer_announcements = []
timer_lock = threading.Lock()


def on_mqtt_message(client, userdata, msg):
    """Handle incoming MQTT messages for timer notifications."""
    try:
        payload = json.loads(msg.payload.decode())
        message = payload.get("message", "Timer complete")
        log.info(f"Timer notification received: {message}", extra={"event": "timer_notification"})
        with timer_lock:
            timer_announcements.append(message)
    except Exception as e:
        log.error(f"Error parsing MQTT message: {e}", extra={"event": "mqtt_error"})


def start_mqtt_listener():
    """Start MQTT client in background thread."""
    client = mqtt.Client()
    client.on_message = on_mqtt_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.subscribe(TIMER_TOPIC)
        log.info(f"Subscribed to MQTT topic: {TIMER_TOPIC}", extra={"event": "mqtt_connected"})
        client.loop_start()
        return client
    except Exception as e:
        log.error(f"MQTT connection failed: {e}", extra={"event": "mqtt_error"})
        return None


def _speak_with_barge_in(recorder, detector, token_iter, on_first_audio=None):
    """Run streamed TTS with concurrent wake word detection for barge-in.

    Opens the mic during TTS playback and monitors for the wake word.
    If detected, stops TTS immediately.

    Returns (response_text, barged_in).
    """
    barged_in = threading.Event()
    stop_monitor = threading.Event()

    def monitor():
        try:
            recorder.open_stream(flush_buffer=True)
            while not stop_monitor.is_set():
                try:
                    chunk = recorder.read_chunk()
                except Exception:
                    break
                if detector.detect(chunk):
                    log.info("Barge-in: wake word during TTS", extra={"event": "barge_in"})
                    barged_in.set()
                    stop_speaking()
                    break
        except Exception as e:
            log.warning(f"Barge-in monitor error: {e}", extra={"event": "barge_in_error"})

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()

    response = speak_streamed(token_iter, on_first_audio=on_first_audio, mute_mic=False)

    stop_monitor.set()
    recorder.close_stream()  # Waits for reader thread, then closes stream
    monitor_thread.join(timeout=5.0)
    if monitor_thread.is_alive():
        log.warning("Barge-in monitor thread did not exit cleanly", extra={"event": "barge_in_hangup"})

    return response, barged_in.is_set()


def main():
    global running
    log.info("Starting voice assistant", extra={"event": "startup"})

    # Start metrics server on port 8001 (non-blocking background thread)
    metrics_server = start_metrics_server(port=8001)
    log.info("Metrics server started on port 8001", extra={"event": "metrics_started"})

    recorder = AudioRecorder()
    detector = WakeWordDetector()
    cooldown_remaining = 0  # Chunks to skip before accepting wake word
    pending_conversation = False  # True after barge-in: skip wake word, enter conversation

    # Start MQTT listener for timer notifications
    mqtt_client = start_mqtt_listener()

    # Handle graceful shutdown
    def shutdown(sig, frame):
        global running
        log.info("Shutting down", extra={"event": "shutdown"})
        running = False
        stop_speaking()
        if mqtt_client:
            mqtt_client.loop_stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        recorder.open_stream()
        LISTENING_STATE.set(1)
        log.info("Listening for wake word", extra={"event": "listening"})

        while running:
            if not pending_conversation:
                try:
                    # Listen for wake word
                    chunk = recorder.read_chunk()
                except IOError as e:
                    # USB stream stall — audio.py already reopened the stream, just retry
                    if not running:
                        break
                    log.warning(f"Audio stream recovered: {e}", extra={"event": "audio_recovery"})
                    detector.reset()
                    cooldown_remaining = COOLDOWN_CHUNKS
                    continue
                except Exception as e:
                    if not running:
                        break
                    raise e

                if not running:
                    break

                # Detect 'alive but deaf' condition: stream returns data but
                # amplitude has been near-zero for too long (PipeWire routing
                # stale / PortAudio lost the input device).
                if not recorder.check_stream_health():
                    STREAM_DEAD_RECOVERIES.inc()
                    recorder.force_reopen()
                    detector.reset()
                    cooldown_remaining = COOLDOWN_CHUNKS
                    continue

                # Check for timer announcements
                with timer_lock:
                    if timer_announcements:
                        announcement = timer_announcements.pop(0)
                        log.info(f"Announcing timer: {announcement}", extra={"event": "timer_announce"})
                        stop_thinking_loop()  # Safety: stop any leftover thinking sounds
                        recorder.close_stream()
                        TTS_REQUESTS.inc()
                        announce_timer(announcement, repeats=3, pause=3.0)
                        time.sleep(AUDIO_SETTLE_PAUSE)
                        detector.reset()
                        recorder.open_stream(flush_buffer=True)
                        cooldown_remaining = COOLDOWN_CHUNKS
                        continue

                # Skip wake word detection during cooldown period
                if cooldown_remaining > 0:
                    cooldown_remaining -= 1
                    continue

                if not detector.detect(chunk):
                    continue

            # === Conversation start ===
            pending_conversation = False
            conversation_start = time.time()
            WAKEWORD_DETECTIONS.inc()
            LISTENING_STATE.set(0)
            log.info("Wake word detected", extra={"event": "wakeword_detected"})
            detector.reset()

            # Close mic before speaking to avoid feedback/self-triggering
            recorder.close_stream()
            TTS_REQUESTS.inc()
            speak("Yes?")
            time.sleep(POST_TTS_PAUSE)

            if not running:
                break

            recorder.open_stream(flush_buffer=False)  # Don't flush - start recording immediately

            # Record user speech (with concurrent STT if enabled)
            record_start = time.time()

            if STREAMING_STT_ENABLED:
                # Streaming: record and transcribe concurrently
                session = recorder.record_until_silence_streaming(max_seconds=MAX_RECORD_SECONDS)
                stt_start = time.time()
                text = transcribe_streaming(session)
                session.thread.join(timeout=2.0)
                recorder.close_stream()
                recording_duration = time.time() - record_start
                RECORDING_DURATION.observe(recording_duration)
                stt_duration = time.time() - stt_start

                audio_data = session.get_audio_snapshot()
                if len(audio_data) < MIN_SPEECH_BYTES:
                    WAKEWORD_FALSE_TRIGGERS.inc()
                    log.info("No speech after wake word", extra={"event": "no_speech"})
                    recorder.open_stream()
                    LISTENING_STATE.set(1)
                    continue
            else:
                # Sequential fallback
                audio_data = recorder.record_until_silence(max_seconds=MAX_RECORD_SECONDS)
                recorder.close_stream()
                recording_duration = time.time() - record_start
                RECORDING_DURATION.observe(recording_duration)

                if len(audio_data) < MIN_SPEECH_BYTES:
                    WAKEWORD_FALSE_TRIGGERS.inc()
                    log.info("No speech after wake word", extra={"event": "no_speech"})
                    recorder.open_stream()
                    LISTENING_STATE.set(1)
                    continue

                stt_start = time.time()
                text = transcribe(audio_data)
                stt_duration = time.time() - stt_start

            STT_DURATION.observe(stt_duration)

            if not text:
                STT_REQUESTS.labels(status="empty").inc()
                log.info("Transcription empty", extra={"event": "stt_empty", "duration_ms": int(stt_duration * 1000)})
                TTS_REQUESTS.inc()
                speak("Sorry, I didn't catch that.")
                time.sleep(POST_EMPTY_PAUSE)
                detector.reset()
                recorder.open_stream(flush_buffer=True)
                cooldown_remaining = COOLDOWN_CHUNKS
                LISTENING_STATE.set(1)
                continue

            STT_REQUESTS.labels(status="success").inc()
            log.info(f"Transcribed: {text}", extra={"event": "stt_success", "duration_ms": int(stt_duration * 1000)})

            # Start thinking sound loop while we wait for LLM
            start_thinking_loop()

            # Stream response from brain → TTS
            brain_start = time.time()
            TTS_REQUESTS.inc()
            barged_in = False

            if BARGE_IN_ENABLED:
                response, barged_in = _speak_with_barge_in(
                    recorder, detector,
                    ask_stream(text),
                    on_first_audio=stop_thinking_loop
                )
            else:
                response = speak_streamed(
                    ask_stream(text),
                    on_first_audio=stop_thinking_loop
                )

            brain_duration = time.time() - brain_start
            BRAIN_DURATION.observe(brain_duration)
            BRAIN_REQUESTS.labels(status="success").inc()

            # Always ensure thinking sound is stopped
            stop_thinking_loop()

            log.info(f"Brain response: {response[:100]}...", extra={
                "event": "brain_response",
                "duration_ms": int(brain_duration * 1000),
                "response_length": len(response)
            })

            if not running:
                break

            # Barge-in: skip follow-up/cleanup, start new conversation immediately
            if barged_in:
                log.info("Barge-in: restarting conversation", extra={"event": "barge_in_restart"})
                pending_conversation = True
                continue

            # Check if response ends with a question - if so, listen for follow-up
            expects_followup = response.strip().endswith("?")

            if expects_followup:
                log.info("Waiting for follow-up", extra={"event": "followup_listening"})
                time.sleep(POST_TTS_PAUSE)
                recorder.open_stream(flush_buffer=True)

                # Listen for follow-up (shorter timeout, same silence detection)
                audio_data = recorder.record_until_silence(max_seconds=FOLLOWUP_MAX_SECONDS)
                recorder.close_stream()

                if len(audio_data) >= MIN_SPEECH_BYTES:  # Got speech
                    stt_start = time.time()
                    followup_text = transcribe(audio_data)
                    stt_duration = time.time() - stt_start
                    STT_DURATION.observe(stt_duration)

                    if followup_text:
                        STT_REQUESTS.labels(status="success").inc()
                        # Check for dismissive responses
                        dismissals = ["no", "nope", "never mind", "nevermind", "that's all", "nothing", "i'm good", "no thanks"]
                        if followup_text.lower().strip().rstrip('.!') in dismissals:
                            log.info(f"Followup dismissed: {followup_text}", extra={"event": "followup_dismissed"})
                            TTS_REQUESTS.inc()
                            speak("Okay!")
                        else:
                            log.info(f"Followup: {followup_text}", extra={"event": "followup_received"})

                            # Process follow-up (streamed, with barge-in)
                            start_thinking_loop()
                            brain_start = time.time()
                            TTS_REQUESTS.inc()

                            if BARGE_IN_ENABLED:
                                followup_response, barged_in = _speak_with_barge_in(
                                    recorder, detector,
                                    ask_stream(followup_text),
                                    on_first_audio=stop_thinking_loop
                                )
                            else:
                                followup_response = speak_streamed(
                                    ask_stream(followup_text),
                                    on_first_audio=stop_thinking_loop
                                )

                            brain_duration = time.time() - brain_start
                            BRAIN_DURATION.observe(brain_duration)
                            BRAIN_REQUESTS.labels(status="success").inc()
                            stop_thinking_loop()

                            log.info(f"Followup response: {followup_response[:100]}...", extra={
                                "event": "followup_response",
                                "duration_ms": int(brain_duration * 1000)
                            })

                            if barged_in:
                                log.info("Barge-in during follow-up", extra={"event": "barge_in_restart"})
                                pending_conversation = True
                                continue
                    else:
                        STT_REQUESTS.labels(status="empty").inc()
                else:
                    log.info("No follow-up detected", extra={"event": "no_followup"})

            # Record conversation metrics
            conversation_duration = time.time() - conversation_start
            CONVERSATIONS_TOTAL.inc()
            CONVERSATION_DURATION.observe(conversation_duration)
            log.info("Conversation complete", extra={
                "event": "conversation_complete",
                "duration_ms": int(conversation_duration * 1000)
            })

            # Reset detector state completely
            detector.reset()

            # Brief wait for audio hardware to settle
            time.sleep(AUDIO_SETTLE_PAUSE)

            # Open stream and aggressively flush any buffered audio
            recorder.open_stream(flush_buffer=True)

            # Additional cooldown to ignore any residual triggers
            cooldown_remaining = COOLDOWN_CHUNKS
            LISTENING_STATE.set(1)
            log.info("Listening for wake word", extra={"event": "listening"})

    except Exception as e:
        log.error(f"Error in main loop: {e}", exc_info=True, extra={"event": "error"})
    finally:
        log.info("Cleaning up", extra={"event": "cleanup"})
        LISTENING_STATE.set(0)
        stop_speaking()
        detector.cleanup()
        recorder.cleanup()
        log.info("Goodbye", extra={"event": "stopped"})


if __name__ == "__main__":
    main()
