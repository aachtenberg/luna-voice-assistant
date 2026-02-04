import numpy as np
import sounddevice as sd
from scipy import signal
from config import (
    DEVICE_SAMPLE_RATE, TARGET_SAMPLE_RATE, CHANNELS,
    DEVICE_CHUNK_SIZE, SILENCE_THRESHOLD, SILENCE_DURATION, MIN_RECORD_SECONDS
)


def resample(audio_data: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
    """Resample audio from orig_rate to target_rate."""
    if orig_rate == target_rate:
        return audio_data
    num_samples = int(len(audio_data) * target_rate / orig_rate)
    return signal.resample(audio_data, num_samples).astype(np.int16)


class AudioRecorder:
    def __init__(self):
        self.stream = None
        self.sample_rate = DEVICE_SAMPLE_RATE
        # Use None = system default (PipeWire will route to the right device)
        self.device_index = None
        print("Using system default audio input (PipeWire managed)")

    def open_stream(self, flush_buffer=False):
        """Open the microphone stream."""
        if self.stream is None:
            # Use configured sample rate - PipeWire handles conversion
            self.sample_rate = DEVICE_SAMPLE_RATE

            # Calculate chunk size for this sample rate (80ms of audio)
            chunk_size = int(self.sample_rate * 0.08)

            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype='int16',
                device=self.device_index,  # None = system default
                blocksize=chunk_size
            )
            self.stream.start()
            print(f"Audio stream opened at {self.sample_rate}Hz")

        # Flush buffer even if stream was already open
        if flush_buffer and self.stream:
            chunk_size = int(self.sample_rate * 0.08)
            for _ in range(15):  # Discard ~1.2 seconds of buffered audio
                try:
                    self.stream.read(chunk_size)
                except:
                    pass
            print("Flushed audio buffer")

    def close_stream(self):
        """Close the microphone stream."""
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def read_chunk(self) -> bytes:
        """Read a chunk of audio data and resample to 16kHz."""
        if self.stream is None:
            self.open_stream()
        chunk_size = int(self.sample_rate * 0.08)
        data, _ = self.stream.read(chunk_size)
        # Flatten and convert
        audio_native = data.flatten().astype(np.int16)
        audio_16k = resample(audio_native, self.sample_rate, TARGET_SAMPLE_RATE)
        return audio_16k.tobytes()

    def record_until_silence(self, max_seconds: float = 10.0) -> bytes:
        """Record audio until silence is detected or max time reached."""
        self.open_stream()
        frames = []
        silent_chunks = 0
        chunk_size = int(self.sample_rate * 0.08)
        chunks_per_second = self.sample_rate / chunk_size
        silence_chunks_needed = int(SILENCE_DURATION * chunks_per_second)
        max_chunks = int(max_seconds * chunks_per_second)
        min_chunks = int(MIN_RECORD_SECONDS * chunks_per_second)  # Minimum before silence detection
        chunk_count = 0

        max_amplitude = 0
        for _ in range(max_chunks):
            data, _ = self.stream.read(chunk_size)
            audio_native = data.flatten().astype(np.int16)
            chunk_count += 1

            amplitude = np.abs(audio_native).mean()
            max_amplitude = max(max_amplitude, amplitude)

            # Check for silence (only after minimum recording time)
            if chunk_count > min_chunks:
                if amplitude < SILENCE_THRESHOLD:
                    silent_chunks += 1
                    if silent_chunks >= silence_chunks_needed:
                        break
                else:
                    silent_chunks = 0

            # Resample and store
            audio_16k = resample(audio_native, self.sample_rate, TARGET_SAMPLE_RATE)
            frames.append(audio_16k.tobytes())

        print(f"Recorded {chunk_count} chunks, max amplitude: {max_amplitude:.0f} (threshold: {SILENCE_THRESHOLD})")
        return b''.join(frames)

    def cleanup(self):
        """Clean up audio resources."""
        self.close_stream()
