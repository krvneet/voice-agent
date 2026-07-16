# Smart Scheduler — Voice AI Agent

A **session-aware, voice-to-voice** AI agent that finds and books meetings on
Google Calendar through natural spoken conversation. Speak your request, and the
agent asks clarifying questions, remembers context across turns, resolves complex
time expressions, handles conflicts gracefully, and books the slot — all with
human-latency spoken replies.

Built with free models only, hosted on GCP. Open the public URL, click **Connect**,
and talk.

> **What it is:** a genuine conversational agent (STT → LLM → TTS cascade with
> full session memory), **not** a one-shot voice command tool. It remembers the
> duration/day/preferences you already gave, asks only for what's missing, handles
> mid-conversation changes ("actually make it an hour"), and supports barge-in.

---

## Architecture

```
Browser (mic+speaker) ──WebRTC──► LiveKit Cloud ──dispatch──► agent-worker (Cloud Run)
      │  HTTPS (public URL)                                       │  AgentSession:
      └──────► web service (Cloud Run) ── /token (JWT) ───────────┘   Silero VAD
               serves static HTML/CSS/JS + livekit-client.umd          → Groq Whisper (STT)
                                                                       → Groq Llama 3.3 70B (LLM + tools)
                                                                       → Kokoro-82M (TTS, in-process)
                                                          tools ─► Google Calendar API (service account)
```

Two Cloud Run services: the **agent worker** (voice pipeline + calendar tools,
Kokoro TTS runs in-process) and the **web** service (static UI + token minting).
Design rationale in [`docs/`](docs/).

## Tech stack (all models free)

| Layer | Choice |
|---|---|
| Voice orchestration | LiveKit Agents (Python) + LiveKit Cloud (free tier) |
| LLM | Groq `llama-3.3-70b-versatile` (free) · fallback Gemini 2.0 Flash (AI Studio, free) |
| STT | Groq `whisper-large-v3-turbo` (free) |
| TTS | Kokoro-82M via `kokoro-onnx`, in-process (open weights) |
| VAD / turn detection | Silero VAD + LiveKit turn detector |
| Calendar | Google Calendar API (service account) |
| Time logic | pure-Python resolver (`dateutil` + `zoneinfo`) |
| Frontend | vanilla HTML/CSS/JS + LiveKit JS SDK (vendored) |
| Hosting | GCP Cloud Run + Secret Manager (hosting only) |

## Repository layout

```
agent/    LiveKit worker: agent.py, scheduler_agent.py, calendar_client.py,
          time_resolver.py, kokoro_tts.py, config.py, Dockerfile
web/      FastAPI token server + static voice UI, Dockerfile
tests/    text-mode scenario tests for the time logic
scripts/  smoke_calendar.py (verify the calendar share)
docs/     design docs (01–08) + GCP setup guide
```

---

## Setup

### 1. Provision services (do this first)
Follow **[docs/08-gcp-setup-guide.md](docs/08-gcp-setup-guide.md)** to create the
free accounts (LiveKit Cloud, Groq, Google AI Studio), the demo Google Calendar
(shared with the service account), and the GCP resources (APIs, Artifact Registry,
service accounts, Secret Manager).

### 2. Configure environment
```bash
cp .env.example .env      # fill in LiveKit, Groq, Gemini keys, calendar id
# place the calendar service-account key as ./gcal-sa.json
```

### 3. Install dependencies
```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r agent/requirements.txt -r web/requirements.txt
```

### 4. Download the Kokoro TTS model (local dev only)
The Docker image bakes these in at build; for local runs, fetch them into
`agent/models/` (they are git-ignored):
```bash
mkdir -p agent/models
curl -L -o agent/models/voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
curl -L -o agent/models/kokoro-v1.0.onnx \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
```

---

## Run locally

```bash
# terminal 1 — agent worker (dev mode)
cd agent && python agent.py dev

# terminal 2 — web UI + token server
cd web && uvicorn server:app --port 8080
```
Open <http://localhost:8080>, click **Connect**, and speak. Grant mic permission.

### Verify without voice
```bash
pytest tests/ -v                    # deterministic time-logic scenarios
python scripts/smoke_calendar.py    # confirm the calendar share works
```

---

## Deploy to GCP

Two Cloud Run services. See **[docs/04-gcp-deployment.md](docs/04-gcp-deployment.md)**
for the full commands, or use the one-shot:
```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=asia-south1,_REPO=smart-scheduler
```
The **`smart-scheduler-web`** Cloud Run URL is the public link you hand to the
client.

---

## How the agent works (design choices)

- **Session memory (two layers).** The LLM keeps rolling chat history; the
  `SchedulerAgent` also holds explicit state (remembered duration, last-offered
  slots) so it never re-asks and can re-run a search when a requirement changes.
- **The LLM does not do date math.** It extracts *semantic* hints (a
  natural-language `day_hint` like "late next week", a `time_of_day` like
  "after 7") and calls tools; the deterministic `time_resolver` converts those +
  the current time into concrete date ranges. This is reliable where LLM date
  arithmetic is not. (See [`agent/time_resolver.py`](agent/time_resolver.py).)
- **Three tools:** `find_availability` (freebusy → free slots, with automatic
  **alternatives** when the window is full — graceful conflict resolution),
  `find_event` (anchor relative requests like "a day after Project Alpha
  Kick-off"), and `book_meeting`.
- **Latency.** Cascade of fast free models (Groq STT/LLM) + in-process Kokoro TTS
  (no network hop), Silero VAD + LiveKit turn detection, targeting <800ms
  end-of-speech → first audio.
- **Frontend.** A single vanilla HTML/CSS/JS page (LiveKit JS SDK vendored, no
  CDN) served by the token server — the public URL the client opens.

Hard cases handled (from the assignment) are covered by tests in
[`tests/test_scenarios.py`](tests/test_scenarios.py): "late next week", "last
weekday of this month", deadline-before-a-time, day-after-an-event, evening +
decompress buffer, and mid-conversation duration changes.

## Known limitations (POC scope)
- Single demo calendar; session memory is per-call (no cross-call persistence).
- A service account on a consumer calendar may not email external attendees.
- Groq free-tier rate limits suit a single-user demo; Gemini AI Studio is the
  configured fallback (`LLM_PROVIDER=gemini`).

## Demo
_A 2–3 minute screen recording will be linked here._
