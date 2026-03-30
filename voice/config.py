import os
from dotenv import load_dotenv

load_dotenv()

# Brain service (running locally on Pi)
BRAIN_URL = os.getenv("BRAIN_URL", "http://localhost:8000")

# Whisper STT (faster-whisper in k3s)
WHISPER_URL = os.getenv("WHISPER_URL", "http://localhost:8000")

# Piper TTS (local binary)
PIPER_PATH = os.getenv("PIPER_PATH", os.path.expanduser("~/piper/piper"))
PIPER_MODEL = os.getenv("PIPER_MODEL", os.path.expanduser("~/piper-voices/en_US-hfc_female-medium.onnx"))

# Wake word engine: "openwakeword" or "porcupine"
WAKEWORD_ENGINE = os.getenv("WAKEWORD_ENGINE", "openwakeword")

# Porcupine settings
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "")
PORCUPINE_MODEL = os.getenv("PORCUPINE_MODEL", os.path.join(os.path.dirname(__file__), "assets", "Yo-Luna_en_raspberry-pi_v4_0_0.ppn"))
PORCUPINE_SENSITIVITY = float(os.getenv("PORCUPINE_SENSITIVITY", "0.5"))

# OpenWakeWord settings
CUSTOM_WAKEWORD_MODEL = os.getenv("CUSTOM_WAKEWORD_MODEL", "")
WAKEWORD_THRESHOLD = float(os.getenv("WAKEWORD_THRESHOLD", "0.5"))

# Audio device settings
DEVICE_SAMPLE_RATE = int(os.getenv("DEVICE_SAMPLE_RATE", "48000"))
TARGET_SAMPLE_RATE = 16000  # Fixed: OpenWakeWord/Whisper requirement
CHANNELS = 1
CHUNK_DURATION = 0.08  # Fixed 80ms: OpenWakeWord frame size requirement

# Audio reliability
AUDIO_READ_TIMEOUT = float(os.getenv("AUDIO_READ_TIMEOUT", "5.0"))
FLUSH_SECONDS = float(os.getenv("FLUSH_SECONDS", "1.2"))

# Silence / recording
SILENCE_THRESHOLD = int(os.getenv("SILENCE_THRESHOLD", "50"))
SILENCE_DURATION = float(os.getenv("SILENCE_DURATION", "0.7"))
MIN_RECORD_SECONDS = float(os.getenv("MIN_RECORD_SECONDS", "1.0"))
MAX_RECORD_SECONDS = float(os.getenv("MAX_RECORD_SECONDS", "10.0"))
FOLLOWUP_MAX_SECONDS = float(os.getenv("FOLLOWUP_MAX_SECONDS", "8.0"))
MIN_SPEECH_BYTES = int(os.getenv("MIN_SPEECH_BYTES", "1600"))

# Wake word detection
MIN_DETECTION_AMPLITUDE = int(os.getenv("MIN_DETECTION_AMPLITUDE", "30"))
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.0"))

# Conversation timing
COOLDOWN_SECONDS = float(os.getenv("COOLDOWN_SECONDS", "1.6"))
POST_TTS_PAUSE = float(os.getenv("POST_TTS_PAUSE", "0.3"))
POST_EMPTY_PAUSE = float(os.getenv("POST_EMPTY_PAUSE", "1.0"))
AUDIO_SETTLE_PAUSE = float(os.getenv("AUDIO_SETTLE_PAUSE", "0.2"))

# Barge-in (interrupt TTS with wake word)
BARGE_IN_ENABLED = os.getenv("BARGE_IN_ENABLED", "true").lower() == "true"

# MQTT settings for timer notifications
MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.0.167")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TIMER_TOPIC = "voice-assistant/timer"

# Streaming STT settings
STREAMING_STT_ENABLED = os.getenv("STREAMING_STT_ENABLED", "true").lower() == "true"
STT_PARTIAL_DELAY = float(os.getenv("STT_PARTIAL_DELAY", "1.5"))
