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
from stt import transcribe
from tts import speak, stop_speaking, announce_timer, start_thinking_loop, stop_thinking_loop
from brain_client import ask
from config import MQTT_BROKER, MQTT_PORT, TIMER_TOPIC
from logging_config import setup_logging
from metrics_server import start_metrics_server
from metrics import (
    WAKEWORD_DETECTIONS, WAKEWORD_FALSE_TRIGGERS,
    RECORDING_DURATION, STT_REQUESTS, STT_DURATION,
    TTS_REQUESTS, BRAIN_REQUESTS, BRAIN_DURATION,
    CONVERSATIONS_TOTAL, CONVERSATION_DURATION, LISTENING_STATE
)

# Setup structured logging (JSON for Loki, plain text if LOG_FORMAT=text)
log = setup_logging(json_output=os.getenv("LOG_FORMAT", "text") != "text")

# Global flag for shutdown
running = True

# Cooldown chunks to ignore after TTS (prevents self-triggering from echo)
COOLDOWN_CHUNKS = 20  # ~1.6 seconds at 80ms per chunk

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


def main():
    global running
    log.info("Starting voice assistant", extra={"event": "startup"})

    # Start metrics server on port 8001 (non-blocking background thread)
    metrics_server = start_metrics_server(port=8001)
    log.info("Metrics server started on port 8001", extra={"event": "metrics_started"})

    recorder = AudioRecorder()
    detector = WakeWordDetector()
    cooldown_remaining = 0  # Chunks to skip before accepting wake word

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
            try:
                # Listen for wake word
                chunk = recorder.read_chunk()
            except Exception as e:
                if not running:
                    break
                raise e

            if not running:
                break

            # Check for timer announcements
            with timer_lock:
                if timer_announcements:
                    announcement = timer_announcements.pop(0)
                    log.info(f"Announcing timer: {announcement}", extra={"event": "timer_announce"})
                    recorder.close_stream()
                    TTS_REQUESTS.inc()
                    announce_timer(announcement, repeats=3, pause=3.0)
                    time.sleep(0.2)
                    detector.reset()
                    recorder.open_stream(flush_buffer=True)
                    cooldown_remaining = COOLDOWN_CHUNKS
                    continue

            # Skip wake word detection during cooldown period
            if cooldown_remaining > 0:
                cooldown_remaining -= 1
                continue

            if detector.detect(chunk):
                conversation_start = time.time()
                WAKEWORD_DETECTIONS.inc()
                LISTENING_STATE.set(0)
                log.info("Wake word detected", extra={"event": "wakeword_detected"})
                detector.reset()

                # Close mic before speaking to avoid feedback/self-triggering
                recorder.close_stream()
                TTS_REQUESTS.inc()
                speak("Yes?")
                time.sleep(0.3)  # Brief pause after TTS

                if not running:
                    break

                recorder.open_stream(flush_buffer=False)  # Don't flush - start recording immediately

                # Record user speech
                record_start = time.time()
                audio_data = recorder.record_until_silence(max_seconds=10)
                recorder.close_stream()
                recording_duration = time.time() - record_start
                RECORDING_DURATION.observe(recording_duration)

                if len(audio_data) < 1600:  # Less than 0.1s of audio
                    WAKEWORD_FALSE_TRIGGERS.inc()
                    log.info("No speech after wake word", extra={"event": "no_speech"})
                    recorder.open_stream()
                    LISTENING_STATE.set(1)
                    continue

                # Transcribe
                stt_start = time.time()
                text = transcribe(audio_data)
                stt_duration = time.time() - stt_start
                STT_DURATION.observe(stt_duration)

                if not text:
                    STT_REQUESTS.labels(status="empty").inc()
                    log.info("Transcription empty", extra={"event": "stt_empty", "duration_ms": int(stt_duration * 1000)})
                    TTS_REQUESTS.inc()
                    speak("Sorry, I didn't catch that.")
                    time.sleep(1.0)
                    detector.reset()
                    recorder.open_stream(flush_buffer=True)
                    cooldown_remaining = COOLDOWN_CHUNKS
                    LISTENING_STATE.set(1)
                    continue

                STT_REQUESTS.labels(status="success").inc()
                log.info(f"Transcribed: {text}", extra={"event": "stt_success", "duration_ms": int(stt_duration * 1000)})

                # Start thinking sound loop while we wait for LLM
                start_thinking_loop()

                # Get response from brain
                brain_start = time.time()
                response = ask(text)
                brain_duration = time.time() - brain_start
                BRAIN_DURATION.observe(brain_duration)
                BRAIN_REQUESTS.labels(status="success").inc()

                # Stop thinking sound
                stop_thinking_loop()

                log.info(f"Brain response: {response[:100]}...", extra={
                    "event": "brain_response",
                    "duration_ms": int(brain_duration * 1000),
                    "response_length": len(response)
                })

                # Speak response (mic is closed, no feedback)
                TTS_REQUESTS.inc()
                speak(response)

                if not running:
                    break

                # Check if response ends with a question - if so, listen for follow-up
                expects_followup = response.strip().endswith("?")

                if expects_followup:
                    log.info("Waiting for follow-up", extra={"event": "followup_listening"})
                    time.sleep(0.3)
                    recorder.open_stream(flush_buffer=True)

                    # Listen for follow-up (shorter timeout, same silence detection)
                    audio_data = recorder.record_until_silence(max_seconds=8)
                    recorder.close_stream()

                    if len(audio_data) >= 1600:  # Got speech
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

                                # Process follow-up
                                start_thinking_loop()
                                brain_start = time.time()
                                followup_response = ask(followup_text)
                                brain_duration = time.time() - brain_start
                                BRAIN_DURATION.observe(brain_duration)
                                BRAIN_REQUESTS.labels(status="success").inc()
                                stop_thinking_loop()

                                log.info(f"Followup response: {followup_response[:100]}...", extra={
                                    "event": "followup_response",
                                    "duration_ms": int(brain_duration * 1000)
                                })
                                TTS_REQUESTS.inc()
                                speak(followup_response)
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
                time.sleep(0.2)

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
