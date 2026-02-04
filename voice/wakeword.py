import os
import numpy as np
from config import (
    WAKEWORD_ENGINE,
    PICOVOICE_ACCESS_KEY, PORCUPINE_MODEL, PORCUPINE_SENSITIVITY,
    CUSTOM_WAKEWORD_MODEL, WAKEWORD_THRESHOLD
)

# Minimum amplitude to even consider wake word detection
MIN_DETECTION_AMPLITUDE = 30


class WakeWordDetector:
    def __init__(self):
        self.engine = WAKEWORD_ENGINE.lower()
        self._porcupine = None
        self._oww_model = None

        if self.engine == "porcupine":
            self._init_porcupine()
        else:
            self._init_openwakeword()

    def _init_porcupine(self):
        """Initialize Picovoice Porcupine."""
        import pvporcupine

        if not PICOVOICE_ACCESS_KEY:
            raise ValueError("PICOVOICE_ACCESS_KEY is required for Porcupine")

        if not os.path.exists(PORCUPINE_MODEL):
            raise FileNotFoundError(f"Porcupine model not found: {PORCUPINE_MODEL}")

        print(f"Loading Porcupine wake word model: {PORCUPINE_MODEL}")
        self._porcupine = pvporcupine.create(
            access_key=PICOVOICE_ACCESS_KEY,
            keyword_paths=[PORCUPINE_MODEL],
            sensitivities=[PORCUPINE_SENSITIVITY]
        )
        print(f"Porcupine initialized (frame_length={self._porcupine.frame_length}, sample_rate={self._porcupine.sample_rate})")

        # Porcupine expects exactly frame_length samples per call
        self._frame_length = self._porcupine.frame_length
        self._buffer = np.array([], dtype=np.int16)

    def _init_openwakeword(self):
        """Initialize OpenWakeWord."""
        from openwakeword.model import Model

        VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))

        if CUSTOM_WAKEWORD_MODEL and os.path.exists(CUSTOM_WAKEWORD_MODEL):
            print(f"Loading custom OpenWakeWord model: {CUSTOM_WAKEWORD_MODEL}")
            self._oww_model = Model(
                wakeword_model_paths=[CUSTOM_WAKEWORD_MODEL],
                vad_threshold=VAD_THRESHOLD if VAD_THRESHOLD > 0 else 0
            )
        else:
            print("Using built-in OpenWakeWord models (say 'hey jarvis')")
            self._oww_model = Model(
                vad_threshold=VAD_THRESHOLD if VAD_THRESHOLD > 0 else 0
            )

        if VAD_THRESHOLD > 0:
            print(f"VAD enabled with threshold: {VAD_THRESHOLD}")

        self._threshold = WAKEWORD_THRESHOLD

    def detect(self, audio_chunk: bytes) -> bool:
        """Check if wake word was detected in the audio chunk."""
        # Convert bytes to numpy array
        audio_data = np.frombuffer(audio_chunk, dtype=np.int16)

        # Check audio amplitude - require meaningful audio level
        amplitude = np.abs(audio_data).mean()
        if amplitude < MIN_DETECTION_AMPLITUDE:
            # Too quiet - skip detection
            if self.engine == "porcupine":
                # Still need to feed data to maintain buffer state
                self._buffer = np.concatenate([self._buffer, audio_data])
                # Discard excess buffer to prevent memory growth
                if len(self._buffer) > self._frame_length * 10:
                    self._buffer = self._buffer[-self._frame_length * 5:]
            elif self._oww_model:
                self._oww_model.predict(audio_data)
            return False

        if self.engine == "porcupine":
            return self._detect_porcupine(audio_data, amplitude)
        else:
            return self._detect_openwakeword(audio_data, amplitude)

    def _detect_porcupine(self, audio_data: np.ndarray, amplitude: float) -> bool:
        """Detect wake word using Porcupine."""
        # Add to buffer
        self._buffer = np.concatenate([self._buffer, audio_data])

        # Process complete frames
        while len(self._buffer) >= self._frame_length:
            frame = self._buffer[:self._frame_length]
            self._buffer = self._buffer[self._frame_length:]

            result = self._porcupine.process(frame)
            if result >= 0:
                print(f"Wake word detected: Yo Luna (amplitude: {amplitude:.0f})")
                return True

        return False

    def _detect_openwakeword(self, audio_data: np.ndarray, amplitude: float) -> bool:
        """Detect wake word using OpenWakeWord."""
        prediction = self._oww_model.predict(audio_data)

        for model_name, score in prediction.items():
            if score > self._threshold:
                print(f"Wake word detected: {model_name} (score: {score:.2f}, amplitude: {amplitude:.0f})")
                return True

        return False

    def reset(self):
        """Reset the model state."""
        print("Resetting wake word detector...")
        if self.engine == "porcupine":
            # Clear the buffer
            self._buffer = np.array([], dtype=np.int16)
        else:
            # Recreate the OpenWakeWord model
            self._init_openwakeword()

    def cleanup(self):
        """Clean up resources."""
        if self._porcupine:
            self._porcupine.delete()
            self._porcupine = None
