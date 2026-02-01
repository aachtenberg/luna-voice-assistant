#!/usr/bin/env python3
"""Voice assistant main loop."""

import signal
import sys
import time
from audio import AudioRecorder
from wakeword import WakeWordDetector
from stt import transcribe
from tts import speak, stop_speaking
from brain_client import ask

# Global flag for shutdown
running = True

# Cooldown chunks to ignore after TTS (prevents self-triggering from echo)
COOLDOWN_CHUNKS = 50  # ~4 seconds at 80ms per chunk


def main():
    global running
    print("Starting voice assistant...")
    print("Listening for wake word... (Ctrl+C to quit)")

    recorder = AudioRecorder()
    detector = WakeWordDetector()
    cooldown_remaining = 0  # Chunks to skip before accepting wake word

    # Handle graceful shutdown
    def shutdown(sig, frame):
        global running
        print("\nShutting down...")
        running = False
        stop_speaking()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        recorder.open_stream()

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

            # Skip wake word detection during cooldown period
            if cooldown_remaining > 0:
                cooldown_remaining -= 1
                detector.reset()  # Keep resetting during cooldown
                continue

            if detector.detect(chunk):
                print("Wake word detected! Listening...")
                detector.reset()

                # Close mic before speaking to avoid feedback/self-triggering
                recorder.close_stream()
                speak("Yes?")
                time.sleep(0.3)  # Brief pause after TTS

                if not running:
                    break

                recorder.open_stream(flush_buffer=False)  # Don't flush - start recording immediately

                # Record user speech
                print("Recording...")
                audio_data = recorder.record_until_silence(max_seconds=10)
                recorder.close_stream()  # Close while processing

                if len(audio_data) < 1600:  # Less than 0.1s of audio
                    print("No speech detected")
                    recorder.open_stream()
                    print("Listening for wake word...")
                    continue

                # Transcribe
                print("Transcribing...")
                text = transcribe(audio_data)

                if not text:
                    print("Could not transcribe")
                    speak("Sorry, I didn't catch that.")
                    time.sleep(1.0)  # Longer pause to let audio settle
                    detector.reset()  # Clear any wake word state from TTS audio
                    recorder.open_stream(flush_buffer=True)  # Discard any buffered audio
                    cooldown_remaining = COOLDOWN_CHUNKS  # Ignore wake words for ~2 seconds
                    print("Listening for wake word...")
                    continue

                print(f"You said: {text}")

                # Get response from brain
                print("Thinking...")
                response = ask(text)

                print(f"Response: {response}")

                # Speak response (mic is closed, no feedback)
                speak(response)
                time.sleep(1.0)  # Longer pause to let audio settle

                if not running:
                    break

                detector.reset()  # Clear any wake word state from TTS audio
                recorder.open_stream(flush_buffer=True)  # Discard any buffered audio
                cooldown_remaining = COOLDOWN_CHUNKS  # Ignore wake words for ~2 seconds
                print("Listening for wake word...")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Cleaning up...")
        stop_speaking()
        recorder.cleanup()
        print("Goodbye!")


if __name__ == "__main__":
    main()
