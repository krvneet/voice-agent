"""Public web service: serves the static voice UI and mints LiveKit tokens.

This is the single public URL handed to the client. The LiveKit API secret stays
here (server-side, used only to sign short-lived per-session JWTs); the browser
only ever receives a token, never the secret.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from livekit import api

load_dotenv()

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Smart Scheduler")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/token")
def token() -> dict:
    """Mint a fresh room + join token for a new voice session."""
    room = f"scheduler-{uuid.uuid4().hex[:8]}"
    identity = f"web-{uuid.uuid4().hex[:8]}"
    grant = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
    )
    jwt = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_name("Web user")
        .with_grants(grant)
        .with_ttl(timedelta(hours=1))
        .to_jwt()
    )
    return {"token": jwt, "url": os.environ["LIVEKIT_URL"], "room": room}


# Static files last so /token and /healthz take precedence.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
