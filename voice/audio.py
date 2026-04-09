import logging
import time
import threading
import numpy as np
import sounddevice as sd
from scipy import signal
from config import (
    DEVICE_SAMPLE_RATE, TARGET_SAMPLE_RATE, CHANNELS,
    CHUNK_DURATION, SILENCE_THRESHOLD, SILENCE_DURATION, MIN_RECORD_SECONDS,
    STT_PARTIAL_DELAY, AUDIO_READ_TIMEOUT, FLUSH_SECONDS,
    STREAM_SILENCE_TIMEOUT, STREAM_DEAD_AMPLITUDE
)

log = logging.getLogger("voice")


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
        self._reader_thread = None  # Track the last read_chunk daemon thread
        self._last_nonsilent_time = time.monotonic()
        print("Using system default audio input (PipeWire managed)")

    def open_stream(self, flush_buffer=False):
        """Open the microphone stream."""
        if self.stream is None:
            # Use configured sample rate - PipeWire handles conversion
            self.sample_rate = DEVICE_SAMPLE_RATE

            # Calculate chunk size for this sample rate
            chunk_size = int(self.sample_rate * CHUNK_DURATION)

            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype='int16',
                device=self.device_index,  # None = system default
                blocksize=chunk_size
            )
            self.stream.start()
            self._last_nonsilent_time = time.monotonic()
            print(f"Audio stream opened at {self.sample_rate}Hz")

        # Flush buffer even if stream was already open
        if flush_buffer and self.stream:
            chunk_size = int(self.sample_rate * CHUNK_DURATION)
            flush_chunks = int(FLUSH_SECONDS / CHUNK_DURATION)
            for _ in range(flush_chunks):
                try:
                    self.stream.read(chunk_size)
                except:
                    pass
            print("Flushed audio buffer")

    def close_stream(self):
        """Close the microphone stream.

        Waits for any in-flight read_chunk daemon thread to finish before
        closing, so we don't pull the stream out from under sounddevice's
        C code (which causes heap corruption / malloc crashes).
        """
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=AUDIO_READ_TIMEOUT + 1)
            self._reader_thread = None
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def read_chunk(self) -> bytes:
        """Read a chunk of audio data and resample to 16kHz.

        Uses a watchdog timeout to recover from USB stream stalls
        (common with Anker S330 on Pi 3 due to isochronous transfer issues).
        """
        if self.stream is None:
            self.open_stream()
        chunk_size = int(self.sample_rate * CHUNK_DURATION)

        result = [None]
        error = [None]

        def _read():
            try:
                data, _ = self.stream.read(chunk_size)
                result[0] = data
            except Exception as e:
                error[0] = e

        reader = threading.Thread(target=_read, daemon=True)
        self._reader_thread = reader
        reader.start()
        reader.join(timeout=AUDIO_READ_TIMEOUT)

        if reader.is_alive():
            # Stream stalled — force-close the stream to unblock the reader,
            # then wait for the thread to actually exit before reopening.
            log.warning("Audio read timed out — USB stream stall detected, reopening stream",
                        extra={"event": "audio_stall", "timeout_s": AUDIO_READ_TIMEOUT})
            if self.stream:
                self.stream.stop()
                self.stream.close()
                self.stream = None
            reader.join(timeout=2)
            self._reader_thread = None
            self.open_stream(flush_buffer=True)
            raise IOError("Audio read timed out — stream reopened")
        self._reader_thread = None

        if error[0] is not None:
            raise error[0]

        data = result[0]
        # Flatten and convert
        audio_native = data.flatten().astype(np.int16)

        # Track amplitude for stream liveness detection
        amplitude = np.abs(audio_native).mean()
        if amplitude > STREAM_DEAD_AMPLITUDE:
            self._last_nonsilent_time = time.monotonic()

        audio_16k = resample(audio_native, self.sample_rate, TARGET_SAMPLE_RATE)
        return audio_16k.tobytes()

    def check_stream_health(self) -> bool:
        """Return True if the stream is delivering real audio data.

        Detects the 'alive but deaf' condition where PipeWire/PortAudio
        silently stops delivering audio but the stream doesn't stall.
        """
        if self.stream is None:
            return True
        silent_duration = time.monotonic() - self._last_nonsilent_time
        return silent_duration < STREAM_SILENCE_TIMEOUT

    def force_reopen(self):
        """Force-close and reopen the audio stream for dead-stream recovery."""
        log.warning(
            "Audio stream appears dead — reopening",
            extra={
                "event": "stream_dead_reopen",
                "silent_seconds": int(time.monotonic() - self._last_nonsilent_time),
            },
        )
        self.close_stream()
        time.sleep(0.5)  # let PipeWire/ALSA settle
        self.open_stream(flush_buffer=True)

    def record_until_silence(self, max_seconds: float = 10.0) -> bytes:
        """Record audio until silence is detected or max time reached."""
        self.open_stream()
        frames = []
        silent_chunks = 0
        chunk_size = int(self.sample_rate * CHUNK_DURATION)
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

    def record_until_silence_streaming(self, max_seconds: float = 10.0):
        """Record audio until silence, yielding buffer snapshots for concurrent STT.

        Returns a StreamingRecordSession that the caller can use to read
        partial audio while recording is still in progress.
        """
        session = StreamingRecordSession()

        def _record():
            try:
                self.open_stream()
                chunk_size = int(self.sample_rate * CHUNK_DURATION)
                chunks_per_second = self.sample_rate / chunk_size
                silence_chunks_needed = int(SILENCE_DURATION * chunks_per_second)
                max_chunks = int(max_seconds * chunks_per_second)
                min_chunks = int(MIN_RECORD_SECONDS * chunks_per_second)
                partial_chunks = int(STT_PARTIAL_DELAY * chunks_per_second)

                silent_chunks = 0
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

                    # Resample and append to shared buffer
                    audio_16k = resample(audio_native, self.sample_rate, TARGET_SAMPLE_RATE)
                    with session.lock:
                        session.buffer.extend(audio_16k.tobytes())

                    # Signal when enough audio for a partial transcription
                    if chunk_count == partial_chunks:
                        session.partial_ready.set()

                print(f"Recorded {chunk_count} chunks, max amplitude: {max_amplitude:.0f} (threshold: {SILENCE_THRESHOLD})")
            finally:
                # Signal partial ready in case we finished before the threshold
                session.partial_ready.set()
                session.recording_done.set()

        session.thread = threading.Thread(target=_record, daemon=True)
        session.thread.start()
        return session

    def cleanup(self):
        """Clean up audio resources."""
        self.close_stream()


class StreamingRecordSession:
    """Holds shared state for concurrent record + transcribe."""

    def __init__(self):
        self.buffer = bytearray()
        self.lock = threading.Lock()
        self.partial_ready = threading.Event()
        self.recording_done = threading.Event()
        self.thread = None

    def get_audio_snapshot(self) -> bytes:
        """Get a copy of all audio recorded so far."""
        with self.lock:
            return bytes(self.buffer)

    def wait_for_partial(self, timeout: float = 5.0) -> bool:
        """Wait until enough audio is available for a partial transcription."""
        return self.partial_ready.wait(timeout=timeout)

    def wait_for_done(self, timeout: float = 15.0) -> bool:
        """Wait until recording is complete."""
        return self.recording_done.wait(timeout=timeout)
