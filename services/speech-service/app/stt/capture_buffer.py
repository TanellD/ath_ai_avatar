"""Bounded lossless buffer одной незакоммиченной voice capture."""

CANONICAL_SAMPLE_RATE = 16_000
CANONICAL_NUM_CHANNELS = 1
CANONICAL_SAMPLE_WIDTH_BYTES = 2
CANONICAL_AUDIO_FORMAT = "pcm_s16le"


class InvalidPcmFrameError(ValueError):
    pass


class CaptureBufferLimitError(ValueError):
    pass


class CaptureBuffer:
    def __init__(self, *, max_duration_seconds: int, max_frame_bytes: int) -> None:
        if max_duration_seconds <= 0 or max_frame_bytes <= 0:
            raise ValueError("capture buffer limits must be positive")
        self._max_bytes = (
            max_duration_seconds
            * CANONICAL_SAMPLE_RATE
            * CANONICAL_NUM_CHANNELS
            * CANONICAL_SAMPLE_WIDTH_BYTES
        )
        self._max_frame_bytes = max_frame_bytes
        self._data = bytearray()

    @property
    def size_bytes(self) -> int:
        return len(self._data)

    @property
    def samples(self) -> int:
        return len(self._data) // CANONICAL_SAMPLE_WIDTH_BYTES

    @property
    def duration_ms(self) -> int:
        return self.samples * 1000 // CANONICAL_SAMPLE_RATE

    def append(self, frame: bytes) -> None:
        if not frame:
            raise InvalidPcmFrameError("PCM frame must not be empty")
        if len(frame) % CANONICAL_SAMPLE_WIDTH_BYTES:
            raise InvalidPcmFrameError("PCM16 frame must contain complete samples")
        if len(frame) > self._max_frame_bytes:
            raise CaptureBufferLimitError("PCM frame exceeds configured limit")
        if len(self._data) + len(frame) > self._max_bytes:
            raise CaptureBufferLimitError("voice capture exceeds configured duration")
        self._data.extend(frame)

    def snapshot(self) -> bytes:
        return bytes(self._data)

    def clear(self) -> None:
        self._data[:] = b"\x00" * len(self._data)
        self._data.clear()

