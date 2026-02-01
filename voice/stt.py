import httpx
import io
import wave
from config import WHISPER_URL, TARGET_SAMPLE_RATE, CHANNELS

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
        response = httpx.post(
            f"{WHISPER_URL}/v1/audio/transcriptions",
            files={"file": ("audio.wav", wav_buffer, "audio/wav")},
            data={"model": "medium", "language": "en"},  # Force English
            timeout=30.0
        )
        response.raise_for_status()
        result = response.json()
        text = result.get("text", "").strip()

        # Filter out known hallucinations
        if is_hallucination(text):
            print(f"Filtered hallucination: '{text}'")
            return ""

        return text
    except Exception as e:
        print(f"Transcription error: {e}")
        return ""
