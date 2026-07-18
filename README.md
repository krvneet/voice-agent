# Smart Scheduler — Voice AI Agent

A **session-aware, voice-to-voice** AI agent that finds and books meetings on
Google Calendar through natural spoken conversation. You speak; it asks
clarifying questions, remembers context across turns, resolves complex time
expressions, handles conflicts gracefully, and books the slot — with
human-latency spoken replies. Deployed on GCP behind a public HTTPS URL.

> **What it is:** a genuine conversational agent (STT → LLM → TTS cascade with
> full session memory), **not** a one-shot voice command tool. It remembers the
> duration/day/preferences you already gave, asks only for what's missing,
> handles mid-conversation changes ("actually make it 30 minutes"), and supports
> barge-in.

---

## Architecture

```
Browser (mic+speaker) ──WebRTC──► LiveKit Cloud ──dispatch──► agent worker
      │  HTTPS (public URL)                                       │  AgentSession:
      └──────► web service ── /token (JWT) ────────────────────────┘   Silero VAD (local)
               serves static HTML/CSS/JS + livekit-client.umd          → STT  (LiveKit Inference)
                                                                       → LLM  (LiveKit Inference) + tools
                                                                       → TTS  (LiveKit Inference)
                                                          tools ─► Google Calendar API (service account)
```

Two services: the **agent worker** (voice pipeline + calendar tools, connects
*out* to LiveKit Cloud) and the **web** service (static UI + token minting, the
public entry point). They never call each other directly — LiveKit Cloud wires
them together via the shared `LIVEKIT_*` credentials.

## Tech stack

STT, LLM and TTS each run through a LiveKit **`FallbackAdapter`** — a primary
model via **LiveKit Inference** with a second model as automatic fallback on
error/timeout. Inference usage is billed to your **LiveKit Cloud credits**.

| Layer | Primary (LiveKit Inference) | Fallback |
|---|---|---|
| Orchestration | LiveKit Agents (Python) + LiveKit Cloud | — |
| LLM | `openai/gpt-4o-mini` | `google/gemini-2.0-flash` |
| STT (streaming) | `assemblyai/universal-streaming` | `deepgram/nova-3` |
| TTS | `cartesia/sonic-3` | `inworld/inworld-tts-1` |
| VAD | Silero (local) | — |
| Turn detection | LiveKit turn detector — `MultilingualModel` (local) | — |
| Calendar | Google Calendar API (service account) | — |
| Time logic | pure-Python resolver (`dateutil` + `zoneinfo`) | — |
| Frontend | vanilla HTML/CSS/JS + LiveKit JS SDK (vendored) | — |
| Hosting | a single VM | — |

## Repository layout

```
agent/    LiveKit worker: agent.py, scheduler_agent.py, calendar_client.py,
          time_resolver.py, config.py, requirements.txt, Dockerfile
web/      FastAPI token server + static voice UI, Dockerfile
tests/    text-mode scenario tests for the time logic (pytest)
scripts/  smoke_calendar.py (verify the calendar share)
deploy/   systemd unit files for running on a VM
run.sh    run both services together on one Linux VM (auto-HTTPS if certs present)
docs/     design docs (01–08) + GCP setup guide
```

---

## Setup

### 1. Accounts / provisioning
- A **LiveKit Cloud** project (gives `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
  `LIVEKIT_API_SECRET`; STT/LLM/TTS run via its Inference, on your credits).
- A **Google Calendar** service account with its JSON key, and the demo calendar
  **shared** with the service-account email.

> STT/LLM/TTS are served by LiveKit Inference and authenticate with your LiveKit
> keys, so **no separate Groq/OpenAI/Gemini keys are required.**

### 2. Install dependencies
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Download local model files (Silero VAD + turn detector)
```bash
python agent/agent.py download-files
```

---

## Run

### Locally (development)
```bash
# terminal 1 — agent worker
python agent/agent.py dev
# terminal 2 — web UI + token server
cd web && uvicorn server:app --port 8080
```
Open <http://localhost:8080>, click **Connect**, allow the mic.

### Verify without voice
```bash
pytest tests/ -v                    # deterministic time-logic scenarios
python scripts/smoke_calendar.py    # confirm the calendar share works
```

---

## How the agent works (design choices)

- **Session memory (two layers).** The LLM keeps rolling chat history; the
  `SchedulerAgent` also holds explicit state (remembered duration, last-offered
  slots) so it never re-asks and can re-run a search when a requirement changes.
- **The LLM does not do date math.** It extracts *semantic* hints (a
  natural-language `day_hint` like "late next week", a `time_of_day` like
  "after 7") and calls tools; the deterministic
  [`agent/time_resolver.py`](agent/time_resolver.py) converts those + the current
  time into concrete date ranges. Reliable where LLM date arithmetic is not.
- **Three tools:** `find_availability` (freebusy → free slots, with automatic
  **alternatives** when the window is full — graceful conflict resolution),
  `find_event` (anchor relative requests like "a day after Project Alpha
  Kick-off"), and `book_meeting`.
- **Resilience.** STT/LLM/TTS each run behind a `FallbackAdapter` (primary →
  fallback), so a provider hiccup degrades gracefully instead of dropping the call.
- **Latency.** Streaming STT + fast LLM/TTS via LiveKit Inference, with Silero
  VAD + the LiveKit turn detector, targeting <800ms end-of-speech → first audio.
- **Frontend.** A single vanilla HTML/CSS/JS page (LiveKit JS SDK vendored, no
  CDN) served by the token server — the public URL the client opens.

Hard cases from the assignment are covered by
[`tests/test_scenarios.py`](tests/test_scenarios.py): "late next week", "last
weekday of this month", deadline-before-a-time, day-after-an-event, evening +
decompress buffer, and mid-conversation duration changes (11 passing tests).

## Known limitations (POC scope)
- Single demo calendar; session memory is per-call (no cross-call persistence).
- A service account on a consumer calendar may not email external attendees.

