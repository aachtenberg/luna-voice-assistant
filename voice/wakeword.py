import os
import numpy as np
from openwakeword.model import Model
from config import CUSTOM_WAKEWORD_MODEL, WAKEWORD_THRESHOLD


class WakeWordDetector:
    def __init__(self):
        # Check for custom wake word model
        if CUSTOM_WAKEWORD_MODEL and os.path.exists(CUSTOM_WAKEWORD_MODEL):
            print(f"Loading custom wake word model: {CUSTOM_WAKEWORD_MODEL}")
            self.model = Model(wakeword_models=[CUSTOM_WAKEWORD_MODEL])
        else:
            # Use bundled models (hey_jarvis, alexa, etc.)
            print("Using built-in wake word models (say 'hey jarvis')")
            self.model = Model()

        self.threshold = WAKEWORD_THRESHOLD

    def detect(self, audio_chunk: bytes) -> bool:
        """Check if wake word was detected in the audio chunk."""
        # Convert bytes to numpy array
        audio_data = np.frombuffer(audio_chunk, dtype=np.int16)

        # Run prediction
        prediction = self.model.predict(audio_data)

        # Check if any wake word model triggered
        for model_name, score in prediction.items():
            if score > self.threshold:
                print(f"Wake word detected: {model_name} (score: {score:.2f})")
                return True

        return False

    def reset(self):
        """Reset the model state."""
        self.model.reset()
