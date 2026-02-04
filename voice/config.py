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

# Wake word engine: "porcupine" or "openwakeword"
WAKEWORD_ENGINE = os.getenv("WAKEWORD_ENGINE", "porcupine")

# Porcupine settings
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "")
PORCUPINE_MODEL = os.getenv("PORCUPINE_MODEL", os.path.join(os.path.dirname(__file__), "assets", "Yo-Luna_en_raspberry-pi_v4_0_0.ppn"))
PORCUPINE_SENSITIVITY = float(os.getenv("PORCUPINE_SENSITIVITY", "0.5"))

# OpenWakeWord settings (fallback)
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
SILENCE_THRESHOLD = int(os.getenv("SILENCE_THRESHOLD", "50"))  # Amplitude threshold for silence detection
SILENCE_DURATION = 0.7  # Seconds of silence to stop recording
MIN_RECORD_SECONDS = 1.0  # Minimum recording time before silence detection starts

# Audio device index (card 2 = USB Audio Device)
AUDIO_DEVICE_INDEX = int(os.getenv("AUDIO_DEVICE_INDEX", "2"))

# MQTT settings for timer notifications
MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.0.167")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TIMER_TOPIC = "voice-assistant/timer"
