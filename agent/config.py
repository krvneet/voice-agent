"""Runtime configuration, loaded once from the environment.

All tunables live here so the rest of the agent code never touches os.environ
directly. Values come from the process environment (Cloud Run secrets) or, for
local development, a .env file at the repo root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Repo root = the directory above agent/. Used to resolve .env and relative file
# paths deterministically, regardless of the process's working directory.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Load .env from the repo root when running locally. In Cloud Run the vars are
# injected directly, and the (absent) .env is silently ignored.
load_dotenv(REPO_ROOT / ".env")


def _resolve_path(p: str) -> str:
    """Resolve a (possibly relative) path against the repo root → absolute str."""
    if not p:
        return p
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return str(path)


@dataclass(frozen=True)
class Settings:
    # LiveKit
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # LLM / STT
    groq_api_key: str
    gemini_api_key: str
    llm_provider: str  # "groq" | "gemini"

    # Calendar
    google_credentials_path: str
    calendar_id: str

    # Behaviour
    timezone: str
    working_hours_start: int
    working_hours_end: int
    tts_voice: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        livekit_url=os.getenv("LIVEKIT_URL", ""),
        livekit_api_key=os.getenv("LIVEKIT_API_KEY", ""),
        livekit_api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        llm_provider=os.getenv("LLM_PROVIDER", "groq").lower().strip(),
        google_credentials_path=_resolve_path(
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "gcal-sa.json")
        ),
        calendar_id=os.getenv("GCAL_CALENDAR_ID", ""),
        timezone=os.getenv("AGENT_TIMEZONE", "Asia/Kolkata"),
        working_hours_start=int(os.getenv("WORKING_HOURS_START", "9")),
        working_hours_end=int(os.getenv("WORKING_HOURS_END", "18")),
        tts_voice=os.getenv("TTS_VOICE", "af_heart"),
    )
