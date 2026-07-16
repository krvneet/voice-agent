"""In-process Text-to-Speech using Kokoro-82M (via kokoro-onnx).

Runs entirely inside the agent worker — no separate service, no network hop.
Implements LiveKit's ``tts.TTS`` interface so the AgentSession can stream audio
straight from Kokoro into the room. The ONNX model is loaded once (in the
worker's prewarm step) and shared across sessions.

Verified against livekit-agents 1.6.5:
  - tts.TTS(capabilities, sample_rate, num_channels)
  - ChunkedStream(*, tts, input_text, conn_options); abstract _run(output_emitter)
  - AudioEmitter.initialize(request_id, sample_rate, num_channels, mime_type, ...)
  - AudioEmitter.push(bytes) / flush()

Kokoro outputs float32 mono @ 24 kHz — matches LiveKit's common TTS rate, so no
resampling is needed; we only convert float32 → 16-bit little-endian PCM.
"""

from __future__ import annotations

import logging

import numpy as np
from livekit.agents import tts, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

logger = logging.getLogger("kokoro-tts")

SAMPLE_RATE = 24_000  # Kokoro native rate
NUM_CHANNELS = 1


class KokoroTTS(tts.TTS):
    def __init__(self, kokoro, *, voice: str = "af_heart", lang: str = "en-us"):
        """``kokoro`` is a ready ``kokoro_onnx.Kokoro`` instance (loaded once)."""
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._kokoro = kokoro
        self._voice = voice
        self._lang = lang

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "KokoroChunkedStream":
        return KokoroChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class KokoroChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        kokoro = self._tts._kokoro  # type: ignore[attr-defined]

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            mime_type="audio/pcm",  # raw 16-bit LE PCM
        )

        # create_stream yields (float32 samples in [-1,1], sample_rate) per segment,
        # so playback can begin before the whole sentence is synthesized.
        stream = kokoro.create_stream(
            self._input_text,  # type: ignore[attr-defined]
            voice=self._tts._voice,  # type: ignore[attr-defined]
            lang=self._tts._lang,  # type: ignore[attr-defined]
        )
        async for samples, _sr in stream:
            pcm16 = np.clip(samples, -1.0, 1.0)
            pcm16 = (pcm16 * 32767.0).astype("<i2").tobytes()
            output_emitter.push(pcm16)

        output_emitter.flush()


def load_kokoro(model_path: str, voices_path: str):
    """Load the Kokoro ONNX model. Call once (worker prewarm)."""
    from kokoro_onnx import Kokoro

    logger.info("loading Kokoro model: %s", model_path)
    return Kokoro(model_path, voices_path)
