import subprocess
import tempfile
import os
import threading
from config import PIPER_PATH, PIPER_MODEL

# Global state for barge-in
_playback_process = None
_playback_lock = threading.Lock()


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
