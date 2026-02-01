import os
from dotenv import load_dotenv

load_dotenv()

# Brain service (running locally on Pi)
BRAIN_URL = os.getenv("BRAIN_URL", "http://localhost:8000")

# Whisper STT (on WSL2 box)
WHISPER_URL = os.getenv("WHISPER_URL", "http://192.168.0.198:8090")

# Piper TTS (local binary)
PIPER_PATH = os.getenv("PIPER_PATH", os.path.expanduser("~/piper/piper"))
PIPER_MODEL = os.getenv("PIPER_MODEL", os.path.expanduser("~/piper-voices/en_US-lessac-medium.onnx"))

# Wake word
# Set CUSTOM_WAKEWORD_MODEL to path of .onnx file for custom wake word (e.g., yo_luna.onnx)
# Leave empty to use built-in models (hey_jarvis, alexa, etc.)
CUSTOM_WAKEWORD_MODEL = os.getenv("CUSTOM_WAKEWORD_MODEL", "")
WAKEWORD_THRESHOLD = float(os.getenv("WAKEWORD_THRESHOLD", "0.5"))

# Audio settings
# Device sample rate (48kHz for USB audio device)
DEVICE_SAMPLE_RATE = 48000
# Target sample rate for processing (16kHz for OpenWakeWord/Whisper)
TARGET_SAMPLE_RATE = 16000
CHANNELS = 1
# Chunk size at device rate (80ms worth of samples at 48kHz)
DEVICE_CHUNK_SIZE = 3840
# Chunk size at target rate (80ms at 16kHz for OpenWakeWord)
TARGET_CHUNK_SIZE = 1280
RECORD_SECONDS = 5  # Max recording time after wake word
SILENCE_THRESHOLD = 500  # Amplitude threshold for silence detection
SILENCE_DURATION = 1.5  # Seconds of silence to stop recording
MIN_RECORD_SECONDS = 1.5  # Minimum recording time before silence detection starts

# Audio device index (card 2 = USB Audio Device)
AUDIO_DEVICE_INDEX = int(os.getenv("AUDIO_DEVICE_INDEX", "2"))
