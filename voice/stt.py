import httpx
import io
import wave
import logging
from config import WHISPER_URL, TARGET_SAMPLE_RATE, CHANNELS

log = logging.getLogger("voice")

TRANSCRIPTION_ENDPOINTS = [
    "/v1/audio/transcriptions",
    "/transcribe",
]

# Known Whisper hallucinations that occur with silence/noise/unclear audio
# These are common phrases Whisper outputs when it has nothing real to transcribe
HALLUCINATION_PHRASES = [
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "like and subscribe",
    "see you next time",
    "see you in the next",
    "goodbye",
    "bye bye",
    "thank you",
    "you",
    "the end",
    "music",
    "applause",
    "silence",
    "...",
    ".",
]


def is_hallucination(text: str) -> bool:
    """Check if transcription is a known Whisper hallucination."""
    if not text:
        return True

    normalized = text.lower().strip().rstrip('.!?,')

    # Check against known hallucinations
    for phrase in HALLUCINATION_PHRASES:
        if normalized == phrase or normalized.startswith(phrase):
            return True

    # Very short single words are often hallucinations
    if len(normalized) < 3:
        return True

    return False


def _parse_transcription_response(response: httpx.Response) -> str:
    """Normalize supported transcription response formats to plain text."""
    content_type = response.headers.get("content-type", "")

    if "application/json" in content_type:
        result = response.json()
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, dict):
            return result.get("text", "").strip()
        return ""

    return response.text.strip()


def _post_transcription_request(wav_buffer: io.BytesIO, timeout: float) -> str:
    """Post audio to the configured STT service, preferring the current API shape."""
    last_error = None

    for endpoint in TRANSCRIPTION_ENDPOINTS:
        wav_buffer.seek(0)
        try:
            response = httpx.post(
                f"{WHISPER_URL}{endpoint}",
                files={"file": ("audio.wav", wav_buffer, "audio/wav")},
                data={"response_format": "json"},
                timeout=timeout,
            )
            if response.status_code == 404 and endpoint != TRANSCRIPTION_ENDPOINTS[-1]:
                continue

            response.raise_for_status()
            return _parse_transcription_response(response)
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code == 404 and endpoint != TRANSCRIPTION_ENDPOINTS[-1]:
                continue
            raise
        except Exception as exc:
            last_error = exc
            raise

    if last_error is not None:
        raise last_error

    return ""


def transcribe(audio_data: bytes) -> str:
    """Send audio to Whisper and get transcription."""
    # Convert raw audio to WAV format
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2)  # 16-bit audio
        wav_file.setframerate(TARGET_SAMPLE_RATE)
        wav_file.writeframes(audio_data)

    wav_buffer.seek(0)

    try:
        text = _post_transcription_request(wav_buffer, timeout=30.0)

        # Filter out known hallucinations
        if is_hallucination(text):
            print(f"Filtered hallucination: '{text}'")
            return ""

        return text
    except Exception as e:
        print(f"Transcription error: {e}")
        return ""


def _audio_to_wav(audio_data: bytes) -> io.BytesIO:
    """Convert raw PCM audio to WAV format."""
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2)
        wav_file.setframerate(TARGET_SAMPLE_RATE)
        wav_file.writeframes(audio_data)
    wav_buffer.seek(0)
    return wav_buffer


def transcribe_streaming(session) -> str:
    """Transcribe concurrently with recording using a StreamingRecordSession.

    Sends a partial request to warm up the server while recording continues,
    then sends the final complete audio once recording is done.
    """
    # Wait for enough audio to send a partial (warm-up) request
    session.wait_for_partial(timeout=5.0)

    if not session.recording_done.is_set():
        # Recording still in progress — send partial audio to warm up the server
        partial_audio = session.get_audio_snapshot()
        if len(partial_audio) > 1600:
            try:
                wav_buf = _audio_to_wav(partial_audio)
                _post_transcription_request(wav_buf, timeout=10.0)
                log.debug("Partial STT warm-up sent", extra={"event": "stt_warmup"})
            except Exception:
                pass  # Warm-up is best-effort

    # Wait for recording to finish
    session.wait_for_done(timeout=15.0)

    # Send the complete audio for final transcription
    final_audio = session.get_audio_snapshot()
    if len(final_audio) < 1600:
        return ""

    return transcribe(final_audio)
