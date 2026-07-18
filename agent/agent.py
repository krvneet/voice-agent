"""Agent worker entrypoint.

Registers a LiveKit Agents worker (with no ``agent_name`` → automatic dispatch,
so it joins every room the browser connects to). Builds one AgentSession per
call, wiring resilient STT/LLM/TTS (LiveKit Inference primaries with fallbacks),
Silero VAD, and the LiveKit turn detector, driven by the SchedulerAgent and its
calendar tools.

Run locally:   python agent.py dev
Run in cloud:  python agent.py start
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from livekit.agents import (
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
)
from livekit.plugins import groq, silero
# Local turn detector disabled — using hosted inference.TurnDetector() instead
# (no local ONNX model, much lighter on a small VM).
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from livekit.agents import llm, stt, tts, inference

from calendar_client import CalendarClient
from config import get_settings
# Kokoro TTS disabled — using LiveKit Inference (Cartesia/Inworld) TTS instead.
# from kokoro_tts import KokoroTTS, load_kokoro
from scheduler_agent import SchedulerAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent")


# Kokoro no longer used:
# _MODELS_DIR = os.path.dirname(os.path.abspath(__file__)) + "/models"


def prewarm(proc: JobProcess) -> None:
    """Load heavy, reusable models once per worker process."""
    proc.userdata["vad"] = silero.VAD.load()
    # Kokoro TTS disabled (in-process model no longer loaded):
    # model_path = os.getenv("KOKORO_MODEL_PATH", f"{_MODELS_DIR}/kokoro-v1.0.onnx")
    # voices_path = os.getenv("KOKORO_VOICES_PATH", f"{_MODELS_DIR}/voices-v1.0.bin")
    # proc.userdata["kokoro"] = load_kokoro(model_path, voices_path)


def _build_llm(settings):
    if settings.llm_provider == "gemini":
        # Gemini via Google AI Studio's OpenAI-compatible endpoint (free tier).
        from livekit.plugins import openai

        logger.info("LLM: Gemini 2.0 Flash (AI Studio)")
        return openai.LLM(
            model="gemini-2.0-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=settings.gemini_api_key,
        )
    logger.info("LLM: Groq Llama 3.3 70B")
    return groq.LLM(model="llama-3.3-70b-versatile")  # GROQ_API_KEY from env


async def entrypoint(ctx: JobContext) -> None:
    settings = get_settings()
    tz_name = settings.timezone
    now = datetime.now(ZoneInfo(tz_name))
    logger.info("session start: room=%s now=%s", ctx.room.name, now.isoformat())

    calendar = CalendarClient(
        settings.google_credentials_path, settings.calendar_id, tz_name
    )
    # tts = KokoroTTS(ctx.proc.userdata["kokoro"], voice=settings.tts_voice)

    resilient_stt = stt.FallbackAdapter(
        [
            inference.STT.from_model_string("assemblyai/universal-streaming:en"),
            inference.STT.from_model_string("deepgram/nova-3"),
        ]
    )

    resilient_llm = llm.FallbackAdapter(
        [
            inference.LLM(model="openai/gpt-4o-mini"),
            inference.LLM(model="google/gemini-2.0-flash"),
        ]
    )

    resilient_tts = tts.FallbackAdapter(
        [
            inference.TTS.from_model_string(
                "cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
            ),
            inference.TTS.from_model_string("inworld/inworld-tts-1"),
        ]
    )

    # session = AgentSession(
    #     stt=groq.STT(model="whisper-large-v3-turbo", language="en"),
    #     llm=_build_llm(settings),
    #     tts=tts,
    #     vad=ctx.proc.userdata["vad"],
    #     turn_detection=MultilingualModel(),
    #     preemptive_generation=True,
    # )

    session = AgentSession(
        stt=resilient_stt,
        llm=resilient_llm,
        tts=resilient_tts,
        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),  # hosted; no local model
        preemptive_generation=True,
    )

    agent = SchedulerAgent(
        calendar=calendar,
        now=now,
        tz_name=tz_name,
        wh_start=settings.working_hours_start,
        wh_end=settings.working_hours_end,
    )

    await session.start(agent=agent, room=ctx.room)
    await ctx.connect()
    await session.generate_reply(
        instructions="Greet the user in one short sentence and ask how you can help schedule their meeting."
    )


if __name__ == "__main__":
    # Bind the worker's health/metrics server to Cloud Run's $PORT so startup
    # probes pass (the worker itself connects OUT to LiveKit Cloud).
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            host="0.0.0.0",
            port=int(os.environ.get("PORT", "8081")),
            # Small-VM tuning: keep only 1 warm process (prod default is 4, which
            # can starve a small VM's CPU) and allow more time for process init.
            num_idle_processes=1,
            initialize_process_timeout=60.0,
        )
    )
