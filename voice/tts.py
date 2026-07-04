import hashlib
import subprocess
import tempfile
import os
import re
import time
import threading
import queue
from config import PIPER_PATH, PIPER_MODEL

# Cache synthesized wavs for short static phrases ("Yes?", "Okay!", ...) so
# repeated prompts skip the ~0.7s Piper synthesis on every wake word.
_CACHE_DIR = os.path.expanduser("~/.cache/luna-tts")
_CACHE_MAX_CHARS = 60


def _synth_to_wav(text: str, out_path: str) -> bool:
    """Run Piper to synthesize text into out_path. Returns True on success."""
    process = subprocess.run(
        [PIPER_PATH, "--model", PIPER_MODEL, "--output_file", out_path],
        input=text.encode(),
        capture_output=True,
        timeout=30
    )
    if process.returncode != 0:
        print(f"Piper error: {process.stderr.decode()}")
        return False
    return True


def _cached_wav(text: str):
    """Return path to a cached wav for a short phrase, synthesizing once."""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        key = hashlib.sha1(f"{PIPER_MODEL}:{text}".encode()).hexdigest()[:16]
        path = os.path.join(_CACHE_DIR, f"{key}.wav")
        if not os.path.exists(path) and not _synth_to_wav(text, path):
            return None
        return path
    except Exception as e:
        print(f"TTS cache error: {e}")
        return None

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
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", action],
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

    tmp_path = None
    try:
        # Short phrases come from the synth cache; longer text is synthesized
        # into a throwaway temp file.
        wav_path = _cached_wav(text) if len(text) <= _CACHE_MAX_CHARS else None
        if wav_path is None:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            if not _synth_to_wav(text, tmp_path):
                return
            wav_path = tmp_path

        # Mute mic to prevent TTS from triggering wake word
        _mute_mic(True)

        # Play the audio using pw-play (PipeWire) for Bluetooth speaker support
        with _playback_lock:
            _playback_process = subprocess.Popen(["pw-play", wav_path])

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
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# Sentence boundary pattern: period/exclamation/question followed by space, or newline
_SENTENCE_END = re.compile(r'[.!?](?:\s+|$)|[\n]')


def _clean_for_tts(text: str) -> str:
    """Remove markdown formatting that TTS would read literally."""
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'_+', '', text)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'`+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# Module-level stop event for streamed TTS barge-in
_stream_stop = threading.Event()


def speak_streamed(token_iter, on_first_audio=None, mute_mic=True):
    """Stream TTS: buffer tokens into sentences, synthesize and play incrementally.

    Args:
        token_iter: Iterator yielding text tokens from the LLM
        on_first_audio: Optional callback when first audio starts playing
        mute_mic: Whether to mute mic during playback (disable for barge-in)

    Returns:
        The full accumulated response text.
    """
    global _playback_process
    _stream_stop.clear()

    sentence_queue = queue.Queue()
    full_text_parts = []

    def producer():
        sentence_buffer = ""
        for token in token_iter:
            if _stream_stop.is_set():
                break
            full_text_parts.append(token)
            sentence_buffer += token
            # Split on sentence boundaries
            while True:
                match = _SENTENCE_END.search(sentence_buffer)
                if not match:
                    break
                sentence = sentence_buffer[:match.end()].strip()
                sentence_buffer = sentence_buffer[match.end():]
                if sentence:
                    sentence_queue.put(sentence)
        # Flush remaining text
        remaining = sentence_buffer.strip()
        if remaining:
            sentence_queue.put(remaining)
        sentence_queue.put(None)  # Sentinel

    producer_thread = threading.Thread(target=producer, daemon=True)
    producer_thread.start()

    first_audio_fired = False
    if mute_mic:
        _mute_mic(True)
    try:
        while True:
            try:
                sentence = sentence_queue.get(timeout=30)
            except queue.Empty:
                break
            if sentence is None or _stream_stop.is_set():
                break

            cleaned = _clean_for_tts(sentence)
            if not cleaned:
                continue

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                proc = subprocess.run(
                    [PIPER_PATH, "--model", PIPER_MODEL, "--output_file", tmp_path],
                    input=cleaned.encode(),
                    capture_output=True,
                    timeout=30
                )
                if proc.returncode != 0:
                    continue

                if not first_audio_fired:
                    if on_first_audio:
                        on_first_audio()
                    first_audio_fired = True

                with _playback_lock:
                    _playback_process = subprocess.Popen(["pw-play", tmp_path])
                _playback_process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                stop_speaking()
            except Exception as e:
                print(f"Streamed TTS error: {e}")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            if _stream_stop.is_set():
                break
    finally:
        if mute_mic:
            _mute_mic(False)
        with _playback_lock:
            _playback_process = None
        producer_thread.join(timeout=2)

    return "".join(full_text_parts)


def stop_speaking():
    """Stop any ongoing TTS playback (for barge-in)."""
    global _playback_process
    _stream_stop.set()  # Also stop streamed TTS pipeline

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
