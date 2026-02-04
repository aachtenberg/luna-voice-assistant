import subprocess
import tempfile
import os
import time
import threading
from config import PIPER_PATH, PIPER_MODEL

# Global state for barge-in
_playback_process = None
_playback_lock = threading.Lock()

# Timer alert sound (louder, more attention-grabbing)
ALERT_SOUND = "/usr/share/sounds/freedesktop/stereo/complete.oga"
# Short blip to indicate recording finished
LISTENING_DONE_SOUND = "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga"
# Thinking sound while waiting for LLM
THINKING_SOUND = "/usr/share/sounds/freedesktop/stereo/dialog-information.oga"


def _mute_mic(mute: bool):
    """Mute or unmute the default audio input source."""
    try:
        action = "1" if mute else "0"
        subprocess.run(
            ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", action],
            capture_output=True,
            timeout=2
        )
    except Exception as e:
        print(f"Mute control error: {e}")


def speak(text: str):
    """Convert text to speech and play it."""
    global _playback_process

    if not text:
        return

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Run Piper to generate audio
        process = subprocess.run(
            [PIPER_PATH, "--model", PIPER_MODEL, "--output_file", tmp_path],
            input=text.encode(),
            capture_output=True,
            timeout=30
        )

        if process.returncode != 0:
            print(f"Piper error: {process.stderr.decode()}")
            return

        # Mute mic to prevent TTS from triggering wake word
        _mute_mic(True)

        # Play the audio using pw-play (PipeWire) for Bluetooth speaker support
        with _playback_lock:
            _playback_process = subprocess.Popen(["pw-play", tmp_path])

        _playback_process.wait(timeout=60)

    except subprocess.TimeoutExpired:
        print("TTS timeout")
        stop_speaking()
    except Exception as e:
        print(f"TTS error: {e}")
    finally:
        # Unmute mic after playback
        _mute_mic(False)
        with _playback_lock:
            _playback_process = None
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def stop_speaking():
    """Stop any ongoing TTS playback (for barge-in)."""
    global _playback_process

    with _playback_lock:
        if _playback_process is not None:
            try:
                _playback_process.terminate()
                _playback_process.wait(timeout=1)
            except:
                try:
                    _playback_process.kill()
                except:
                    pass
            _playback_process = None
            print("Playback interrupted")
            return True
    return False


def is_speaking() -> bool:
    """Check if TTS is currently playing."""
    with _playback_lock:
        return _playback_process is not None and _playback_process.poll() is None


def play_alert_sound():
    """Play the alert/alarm sound."""
    if os.path.exists(ALERT_SOUND):
        try:
            subprocess.run(["pw-play", ALERT_SOUND], timeout=5)
        except Exception as e:
            print(f"Alert sound error: {e}")


def play_listening_done():
    """Play a short blip to indicate recording finished."""
    if os.path.exists(LISTENING_DONE_SOUND):
        try:
            subprocess.run(["pw-play", LISTENING_DONE_SOUND], timeout=3, capture_output=True)
        except Exception as e:
            print(f"Blip sound error: {e}")


_thinking_stop = threading.Event()
_thinking_thread = None


def play_thinking_sound():
    """Play a sound to indicate processing/thinking (single play)."""
    if os.path.exists(THINKING_SOUND):
        try:
            subprocess.run(["pw-play", THINKING_SOUND], timeout=3, capture_output=True)
        except Exception as e:
            print(f"Thinking sound error: {e}")


def start_thinking_loop():
    """Start looping the thinking sound in background."""
    global _thinking_thread
    _thinking_stop.clear()

    def loop():
        while not _thinking_stop.is_set():
            if os.path.exists(THINKING_SOUND):
                try:
                    subprocess.run(["pw-play", THINKING_SOUND], timeout=3, capture_output=True)
                except:
                    pass
            # Pause between loops
            _thinking_stop.wait(1.5)

    _thinking_thread = threading.Thread(target=loop, daemon=True)
    _thinking_thread.start()


def stop_thinking_loop():
    """Stop the thinking sound loop."""
    global _thinking_thread
    _thinking_stop.set()
    if _thinking_thread:
        _thinking_thread.join(timeout=1)
        _thinking_thread = None


def announce_timer(message: str, repeats: int = 3, pause: float = 2.0):
    """
    Announce a timer with sound and repeated message.

    Args:
        message: The announcement text
        repeats: Number of times to repeat the announcement
        pause: Seconds to pause between repeats
    """
    # Mute mic during entire announcement sequence
    _mute_mic(True)

    try:
        # Pattern: 3 bings, message, pause, 3 bings, message, pause, 3 bings, message
        for i in range(repeats):
            # Play 3 bings before each announcement
            for _ in range(3):
                play_alert_sound()
                time.sleep(0.5)

            # Wait for bings to finish before speaking
            time.sleep(0.8)

            # Generate and play speech
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                process = subprocess.run(
                    [PIPER_PATH, "--model", PIPER_MODEL, "--output_file", tmp_path],
                    input=message.encode(),
                    capture_output=True,
                    timeout=30
                )

                if process.returncode == 0:
                    subprocess.run(["pw-play", tmp_path], timeout=30)

            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            # Pause between repeats (except after last one)
            if i < repeats - 1:
                time.sleep(pause)

    finally:
        _mute_mic(False)
