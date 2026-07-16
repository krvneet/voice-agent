# 03 — System Architecture

How the pieces from [02-tech-stack.md](02-tech-stack.md) fit together, how data
flows through a turn, and how the <800ms latency budget is met.

---

## 1. Component diagram

```
                            ┌──────────────────────────────────────────┐
                            │                GCP Project                 │
                            │                                            │
  ┌──────────┐   HTTPS      │  ┌───────────────────┐                     │
  │ Browser  │─────────────────▶│ Frontend + Token  │  (Cloud Run,       │
  │ (mic +   │   (public URL)│  │ endpoint (FastAPI │   public HTTPS)     │
  │  speaker)│               │  └─────────┬─────────┘                     │
  └────┬─────┘               │            │ issues LiveKit JWT            │
       │  WebRTC (audio)     │            ▼                               │
       │                     │  ┌───────────────────┐  reads secrets     │
       │             ┌───────────│  Secret Manager   │◀───────────┐       │
       │             │       │  └───────────────────┘            │       │
       │             │       │  ┌────────────────────────────────┴────┐  │
       ▼             ▼       │  │   Agent Worker (Cloud Run, warm)     │  │
  ┌─────────────────────┐   │  │   LiveKit Agents (Python)            │  │
  │   LiveKit Cloud     │◀──────▶  AgentSession:                      │  │
  │  (WebRTC SFU/media) │   │  │    VAD → STT → LLM(+tools) → TTS      │  │
  └─────────────────────┘   │  └──────┬──────────┬──────────┬─────────┘  │
                            │         │          │          │            │
                            └─────────┼──────────┼──────────┼────────────┘
                                      ▼          ▼          ▼
                                ┌─────────┐ ┌─────────┐ ┌──────────────┐
                                │  Groq   │ │  Groq   │ │  Kokoro TTS  │
                                │ Whisper │ │Llama3.3 │ │ (in-process, │
                                │  (STT)  │ │70B (LLM)│ │  in worker)  │
                                └─────────┘ └────┬────┘ └──────────────┘
                     (Groq = free-tier API; Kokoro = free open model, runs in the worker)
                                                 │ function calls
                                                 ▼
                                        ┌──────────────────┐
                                        │ Google Calendar  │
                                        │     API v3       │
                                        └──────────────────┘
```

## 2. Turn data flow (one round of conversation)

1. **Capture** — browser streams mic audio over WebRTC to LiveKit Cloud.
2. **VAD + turn detection** — the worker detects the user has finished speaking
   (Silero VAD + LiveKit semantic turn detector).
3. **STT** — Groq Whisper returns a final transcript.
4. **LLM** — transcript + chat history + session state + *current datetime* go to
   the LLM (Groq Llama / Gemini AI Studio). It either (a) asks a clarifying
   question, or (b) emits a **function call** (`find_slots`, `find_event`,
   `book_meeting`).
5. **Tool execution** — the worker runs the Python tool: constraint object →
   date-range resolver → Google Calendar API (free/busy or event insert) →
   structured result back to the LLM.
6. **Response generation** — the LLM turns the tool result into a natural spoken
   reply, streamed token-by-token.
7. **TTS** — self-hosted Kokoro/Piper streams audio as tokens arrive; LiveKit
   plays it back to the browser. Barge-in cancels playback if the user talks.

Steps 4–6 may loop (multi-step tool use, e.g. `find_event` then `find_slots`).

## 3. Latency budget (<800ms target)

Measured from **end-of-user-speech** to **first audio byte of the reply**, for a
turn that requires **no calendar call** (the common clarifying-question turn):

Free-model budget (Groq STT/LLM + self-hosted Kokoro/Piper TTS):

| Stage | Budget |
|---|---|
| Turn-end detection (VAD/endpointing) | ~50–150ms |
| STT finalization (Groq Whisper) | ~100–250ms |
| LLM time-to-first-token (Groq Llama 3.3 70B) | ~150–350ms |
| TTS time-to-first-byte (Kokoro/Piper on Cloud Run CPU) | ~150–350ms |
| Network / transport overhead | ~50–100ms |
| **Total (no tool call)** | **~500–800ms — at the edge of budget ⚠️** |

The in-process TTS (CPU) is the pinch point. Levers to stay under 800ms:
- **Piper** instead of Kokoro when latency-critical (lightest CPU TTS).
- Give the TTS Cloud Run service enough CPU (`--cpu=2`) + keep it warm.
- Groq's LLM/STT speed offsets much of the TTS cost.

Turns that hit Google Calendar add the API round-trip (~150–400ms). Mitigations:
- Speak a **filler/acknowledgement** first ("Let me check…") so *perceived*
  latency stays low while the calendar query runs.
- Cache the calendar free/busy window for the session to avoid repeat queries.
- Run tool calls concurrently with starting the spoken preamble.

## 4. Component responsibilities

| Component | Responsibility |
|---|---|
| **Frontend + token service (Cloud Run, FastAPI)** | Serve the static `index.html`/`css`/`js` voice UI (LiveKit JS SDK vendored locally); mint short-lived LiveKit access tokens (JWT) at `/token` using the LiveKit API key/secret; never expose provider keys or the LiveKit secret to the browser. This is the public URL handed to the client. |
| **LiveKit Cloud** | WebRTC media transport, room management, SFU. |
| **Agent worker (Cloud Run)** | Runs `AgentSession`; owns the STT/LLM/TTS pipeline, session state, tool functions, and prompt. Stateful per active call, warm via `min-instances=1`. |
| **Kokoro TTS (in-process)** | Runs inside the worker via `kokoro-onnx`; the custom LiveKit TTS streams PCM straight into the room — no separate service, no HTTP hop. |
| **LLM (Groq / Gemini AI Studio)** | Constraint extraction, tool-call decisions, natural-language replies. |
| **Calendar tools** | Deterministic date resolution + Calendar API calls. |
| **Secret Manager** | Stores LiveKit keys, Groq/Gemini-AI-Studio API keys, calendar service-account JSON. |

## 5. State management

- **Chat context**: managed by LiveKit `AgentSession` (rolling message history).
- **Structured session state** (explicit object the tools read/write):
  ```
  SessionState {
    duration_minutes: int | None       # remembered across turns (F1)
    day_preference: str | None          # "tuesday", "next week"...
    time_preference: str | None         # "afternoon", "after 19:00"...
    constraints: list                    # negatives, buffers, deadlines
    timezone: str                        # from env (POC)
    last_offered_slots: list            # so "the first one" resolves
    reference_event: Event | None       # for "after Project Alpha Kick-off"
  }
  ```
- Lives in memory for the duration of the call (no DB needed for POC).
  Requirement changes (F9) mutate one field and re-run the search.

## 6. Failure & edge handling

| Failure | Handling |
|---|---|
| No slots in requested window | `find_slots` returns nearest alternatives; prompt instructs proactive suggestion (F7). |
| Ambiguous request | LLM asks one targeted clarifying question (F2) rather than guessing. |
| Calendar API error / timeout | Tool returns a typed error; agent apologizes and retries/asks to try later. |
| STT mishears | Agent confirms critical facts ("a 1-hour meeting Tuesday, correct?"). |
| User interrupts (barge-in) | LiveKit cancels TTS playback and re-listens. |
| Worker cold start | `min-instances=1` keeps it warm; healthcheck endpoint. |
