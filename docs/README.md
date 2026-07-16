# Smart Scheduler AI Agent — Technical Documentation

A voice-enabled AI agent that helps a user find and schedule a meeting through a
natural, low-latency, multi-turn spoken conversation, backed by Google Calendar.

This folder contains **all technical specs and stack decisions required before
implementation begins.** No application code is written yet — this is the
"decide the stack and prove it can run in the cloud" phase.

---

> **Constraints (locked):** free models only (no paid LLM/STT/TTS); **GCP for
> hosting only** — Cloud Run / Secret Manager / Artifact Registry / Cloud Build /
> Logging, **not** paid GCP AI services (Vertex AI, Cloud STT/TTS).

## What it is

A **session-aware, voice-to-voice conversational agent** — not a one-shot
"speak a command → do a task → reply" tool. Within a call it remembers what you
said (duration, day, preferences), asks only for what's missing, handles
follow-ups and mid-conversation changes, and supports barge-in. Memory lives in
two layers: the LLM's rolling chat history + an explicit session-state object the
tools read/write. (Cross-call persistence is out of POC scope.)

## TL;DR — Recommended Stack (all models free)

| Layer | Choice | Why |
|---|---|---|
| **Voice orchestration** | **LiveKit Agents (Python)** on **LiveKit Cloud** (free tier) | Purpose-built STT→LLM→TTS pipeline, WebRTC transport, turn detection, interruption handling — the single biggest lever for hitting <800ms. OSS + free tier. |
| **LLM (the "brain")** | **Groq — Llama 3.3 70B** (free tier) | Fastest free inference, native tool-calling. **Gemini 2.0 Flash via Google AI Studio free tier** as drop-in fallback. |
| **STT (speech→text)** | **Groq Whisper large-v3-turbo** (free tier) | Fast free hosted Whisper. Self-hosted `faster-whisper` on Cloud Run as fallback. |
| **TTS (text→speech)** | **Kokoro-82M self-hosted on Cloud Run** | Open weights, good quality on CPU. **Piper** for lowest latency. Uses GCP purely for hosting. |
| **Calendar tool** | **Google Calendar API** (free) via **service account** (POC) | Headless, no per-request OAuth dance. OAuth path documented for real end-user calendars. |
| **Time parsing** | **LLM function-calling → structured constraints → Python (`dateutil`/`zoneinfo`) resolver** | Deterministic date math in code; fuzzy language handled by the LLM. |
| **Frontend** | **Minimal static HTML/CSS/JS + LiveKit JS SDK** | No framework/build step; served by the FastAPI token service; a public URL you own to hand to the client. |
| **Cloud** | **Google Cloud Platform (hosting only)** | Agent worker + frontend/token service + self-hosted TTS on **Cloud Run**; secrets in **Secret Manager**. |
| **Public access** | **Cloud Run HTTPS URL** (frontend) + **LiveKit Cloud** (media) | Fully public, no VPN, TLS by default; client opens the link and talks. |

**End-to-end target latency: <800ms** user-stops-speaking → agent-starts-speaking
(tighter headroom with free/self-hosted TTS — see [03-architecture.md](03-architecture.md)).

---

## Document Index

| # | Document | What it covers |
|---|---|---|
| 01 | [Requirements Analysis](01-requirements-analysis.md) | The assignment decomposed into concrete, testable capabilities. |
| 02 | [Tech Stack Decisions](02-tech-stack.md) | Every technology choice with comparison tables and rationale. **← the main deliverable.** |
| 03 | [System Architecture](03-architecture.md) | Components, data flow, latency budget, sequence diagrams. |
| 04 | [GCP Deployment](04-gcp-deployment.md) | How every piece runs in the cloud with a public URL; costs. |
| 05 | [Google Calendar Integration](05-calendar-integration.md) | Auth model, scopes, API calls, tool schemas. |
| 06 | [Agent & Conversation Design](06-agent-conversation-design.md) | Prompting, state, tool-calling logic, conflict resolution, time parsing. |
| 07 | [Assumptions & Open Questions](07-assumptions-and-open-questions.md) | Decisions taken by default + what to confirm before/after the POC. |
| 08 | [GCP & Services Setup Guide](08-gcp-setup-guide.md) | Copy-paste provisioning: external accounts, APIs, service accounts, secrets. **← do this now.** |

---

## What "done" looks like for the POC

1. Open a public HTTPS URL in a browser.
2. Click "Connect", speak: *"I need to schedule a 1-hour meeting Tuesday afternoon."*
3. The agent replies with synthesized speech within ~800ms, remembers context
   across turns, queries a real Google Calendar, offers real free slots, handles
   conflicts gracefully, and books the chosen slot.
4. A 2–3 min screen recording demonstrates the above.
