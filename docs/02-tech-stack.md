# 02 — Tech Stack Decisions

This is the primary deliverable you asked for: **every technology choice with
the reasoning and the alternatives**, so the stack is finalized before writing
implementation code.

Guiding constraints (from [01](01-requirements-analysis.md)): voice in/out,
<800ms latency, stateful multi-turn, Google Calendar tools, deployed on GCP with
a public URL, buildable as a POC in ~5 days.

> **Hard constraints (updated):**
> 1. **Free models only** — no paid LLM/STT/TTS APIs. Models come from free-tier
>    APIs or open weights we self-host.
> 2. **GCP = hosting only** — use GCP for Cloud Run, Secret Manager, Artifact
>    Registry, Cloud Build, and Logging. Do **not** use paid GCP AI services
>    (Vertex AI, Google Cloud Speech-to-Text/Text-to-Speech).

---

## Decision 1 — Voice orchestration: **LiveKit Agents** ✅

**The single most important decision.** The assignment offers "build the stack"
(wire STT + LLM + TTS yourself) vs. a managed realtime path. The real fork is
*what framework orchestrates the turn-taking, streaming, and interruption
handling.* Doing that by hand is where voice projects die on latency and
robustness.

| Option | Verdict |
|---|---|
| **LiveKit Agents (Python) + LiveKit Cloud** | ✅ **Chosen.** Framework built exactly for STT→LLM→TTS voice agents. Handles WebRTC transport, VAD, semantic turn detection, barge-in, streaming, and tool-calling glue. Plugins for every provider below. LiveKit Cloud gives managed media servers + a public URL with a free tier. |
| Roll-your-own (WebSocket + browser MediaRecorder + manual VAD) | ❌ Weeks of undifferentiated plumbing; hard to hit <800ms; interruption handling is a research problem on its own. |
| Gemini Live API / OpenAI Realtime, self-wired | ⚠️ Low latency but you still need transport, turn detection, and reliable tool-calling. Also less control over the calendar tool loop. Kept as a *pipeline option inside LiveKit* (see Decision 3), not as the orchestrator. |
| Pipecat (alternative agent framework) | ⚠️ Viable and similar in spirit; LiveKit chosen for its managed Cloud + first-class GCP/Cloud Run deploy guides + stronger prebuilt web UI. |

**Why LiveKit over "GCP-only" for voice:** GCP has excellent *components* (Speech-to-Text,
Text-to-Speech, Gemini Live) but **no turnkey voice-agent orchestration
framework**. You'd assemble it yourself. LiveKit is the orchestration layer; GCP
is where it's deployed and (optionally) where the STT/TTS/LLM come from. The two
are complementary, not either/or.

**LiveKit Cloud vs self-hosting LiveKit on GCP:** use **LiveKit Cloud** for the
POC (zero media-server ops, free tier covers demo traffic). Self-hosting the
LiveKit SFU on GKE is documented as a later option but adds ops overhead with no
POC benefit.

---

## Decision 2 — LLM (the brain): **Groq — Llama 3.3 70B (free tier)** ✅

**Free-model constraint applies.** All options below are free-tier APIs (no paid
plans, no GCP AI billing).

| Option | Latency | Function calling | Free? | Verdict |
|---|---|---|---|---|
| **Groq — Llama 3.3 70B Versatile** | Fastest (Groq LPU) | Native tool-calling | ✅ Free tier | ✅ **Chosen.** Fastest free inference available — a big help to the latency budget — with solid tool-calling for the calendar functions. |
| **Google Gemini 2.0 Flash (AI Studio Developer API)** | Very low | Strong, native | ✅ Free tier | ⚠️ **Fallback.** Free-tier Gemini *Developer* API (`generativelanguage.googleapis.com`) — free and separate from GCP/Vertex billing. One-line swap in the LiveKit LLM plugin. |
| Groq — Llama 3.1 8B Instant | Extremely low | OK | ✅ Free tier | ⚠️ Cheapest/fastest but weaker on ambiguous time reasoning; keep for latency A/B. |
| OpenRouter free models (e.g. Llama variants) | Varies | Varies | ✅ Some free | ⚠️ Backup source of free models if Groq/Gemini quotas are hit. |
| Gemini 2.5 Flash (Vertex AI), GPT-4o | Low | Excellent | ❌ Paid | ❌ Excluded by the free-model constraint. |

**Rationale:** the scheduler's reasoning load is modest (extract constraints,
decide which tool to call, phrase a reply), so a fast free model is a good fit.
Groq's inference speed directly buys latency headroom, which matters more now
that TTS is self-hosted (Decision 5). Because LiveKit abstracts the LLM behind a
plugin interface, Groq↔Gemini-AI-Studio is a config change — de-risking the
choice.

> **Free-tier caveats:** Groq and Gemini AI Studio both enforce RPM/RPD rate
> limits and may use free-tier inputs for product improvement. Fine for a
> single-user POC against a demo calendar; noted for the live recording.

---

## Decision 3 — Pipeline shape: **cascade (STT→LLM→TTS), not speech-to-speech** ✅

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| **Cascade: Whisper STT → Llama/Gemini LLM → Kokoro TTS** (all free) | Full control over the tool-calling loop; swap any component; easy to log/trace; deterministic function calling; each stage individually free | Slightly more moving parts | ✅ **Chosen.** Reliable tool calls + observability, and every stage can be a free model. |
| Realtime speech-to-speech (Gemini Live / OpenAI Realtime) | Lowest raw latency | Paid, or free-tier with tight limits; tool-calling + calendar integration less controllable; harder to debug | ❌ Not for POC — the strong free realtime options are paid/limited, and it fights the free-model + control requirements. LiveKit's `RealtimeModel` keeps the door open later. |

The cascade is what makes this a **session-aware conversational chatbot** rather
than a one-shot voice command: the LLM sits in the middle holding the full chat
history + session state across turns. It stays within (a tighter, but workable)
<800ms budget — see [03-architecture.md](03-architecture.md) — while keeping the
calendar tool loop transparent and testable, which is exactly what this
assignment grades.

---

## Decision 4 — STT: **Groq Whisper large-v3-turbo (free)** ✅

**Free-model constraint applies.**

| Option | Latency | Free? | Notes |
|---|---|---|---|
| **Groq Whisper large-v3-turbo** (API) | Low (Groq speed) | ✅ Free tier | ✅ **Chosen.** Fast free hosted Whisper; strong accuracy; no self-host compute. |
| **`faster-whisper` self-hosted on Cloud Run** | Med (CPU-bound) | ✅ Free (compute only) | ⚠️ Pure fallback if Groq quota is hit — uses GCP hosting, no external dependency, but CPU latency is higher. |
| Deepgram Nova-3 | ~150–300ms | ❌ Paid (credits) | ❌ Excluded by the free-model constraint. |
| Google Cloud Speech-to-Text v2 | ~300–500ms | ❌ Paid GCP AI service | ❌ Excluded by "GCP = hosting only". |

## Decision 5 — TTS: **Kokoro-82M self-hosted on Cloud Run (free)** ✅

**Free-model constraint applies.** This is the hardest layer to keep free at low
latency — good open TTS must be self-hosted, which fits "GCP = hosting" perfectly.

| Option | Latency | Free? | Notes |
|---|---|---|---|
| **Kokoro-82M** (in-process, via `kokoro-onnx`) | Near real-time on CPU | ✅ Free (open weights) | ✅ **Chosen.** Best quality-per-compute open TTS; runs **in-process inside the worker** (no separate service, no HTTP hop) via a custom LiveKit TTS. Model baked into the worker image. |
| **Piper** (self-hosted) | Fastest on CPU | ✅ Free (open) | ⚠️ **Latency fallback.** Lower-latency, lighter, slightly less natural — swap in if the budget is tight during the demo. |
| Edge-TTS (unofficial Microsoft Edge) | Low | ✅ Free | ⚠️ Good quality and free, but unofficial API (ToS-gray) — kept only as an emergency option. |
| Cartesia / ElevenLabs / Google Cloud TTS | Low | ❌ Paid | ❌ Excluded by the constraints. |

**Note on the model layer:** with these choices, **every model is free** and the
only spend is GCP hosting compute (Cloud Run) + the free-tier external LLM/STT
APIs (Groq/Gemini AI Studio). The all-open pure-GCP variant — `faster-whisper` +
a local Llama (if a free API is unavailable) + Kokoro, all self-hosted — removes
every external dependency at the cost of latency and heavier Cloud Run sizing.

---

## Decision 6 — Calendar: **Google Calendar API via service account** ✅

Auth model detailed in [05-calendar-integration.md](05-calendar-integration.md).

| Auth model | Fit for POC | Verdict |
|---|---|---|
| **Service account + a shared/dedicated demo calendar** | Headless, no interactive consent per session, perfect for a demo agent | ✅ **Chosen.** |
| OAuth 2.0 user consent (Authorization Code flow) | Needed to touch a *real end-user's* personal calendar | ⚠️ Documented for the "real user" case; adds a consent screen + token storage, unnecessary for POC. |
| Domain-wide delegation (Workspace) | Impersonate org users | ❌ Requires Workspace admin; out of scope. |

## Decision 7 — Time parsing: **LLM extracts constraints → Python resolves** ✅

Do **not** let the LLM do date arithmetic. The LLM (via function-call arguments)
emits a structured constraint object; deterministic Python (`datetime`,
`zoneinfo`, `dateutil`) computes concrete date ranges against "now" and the
calendar. Rationale and schema in [06-agent-conversation-design.md](06-agent-conversation-design.md).

## Decision 8 — Frontend: **Minimal static HTML/CSS/JS + LiveKit web SDK** ✅

A single hand-written **`index.html` + `style.css` + `app.js`** (~100 lines of
vanilla JS) using the **LiveKit JavaScript client SDK**. No framework, no build
step, no Next.js. It handles: a Connect button, mic capture, playback of the
agent's audio, a live transcript, and a simple speaking/waveform indicator.

| Option | Verdict |
|---|---|
| **Vanilla static HTML/CSS/JS + LiveKit JS SDK** | ✅ **Chosen.** Simplest possible; a public URL you own; scores well on "built it myself"; keeps the full LiveKit low-latency pipeline. |
| Next.js / React starter | ❌ Rejected — build step + framework overhead the user explicitly doesn't want. |
| Streamlit (`streamlit-webrtc`) | ❌ Would force dropping LiveKit (aiortc-based), rebuilding VAD/turn-detection, risking the <800ms + naturalness grading. |
| LiveKit hosted Sandbox | ❌ Not used — LiveKit-branded URL, may expire / carry free-tier limits; we want a stable client-facing link we own. |

**Delivery model:** the static files are **served by the same Python (FastAPI)
token service on Cloud Run** (see Decision 9), so the frontend and the
`/token` endpoint are one small service and one public URL to hand to the client.

**Vendor the SDK locally:** download the LiveKit client UMD bundle into the
static folder (rather than a runtime CDN link) so the handed-over link has **no
external CDN dependency** and keeps working regardless of CDN/CSP issues.

## Decision 9 — Cloud: **GCP (Cloud Run)** ✅

Full deployment topology, sizing, and cost in [04-gcp-deployment.md](04-gcp-deployment.md).

- **Agent worker** (LiveKit Agents Python process) → **Cloud Run**, `min-instances=1`
  so it stays warm and connected to LiveKit Cloud (no cold-start latency).
- **Frontend (static HTML/CSS/JS) + `/token` endpoint** → one **FastAPI service
  on Cloud Run** (the public HTTPS URL handed to the client).
- **Secrets** (API keys, service-account JSON) → **Secret Manager**.
- **Kokoro TTS** runs **in-process inside the worker** (no separate service).
- **Media transport** → **LiveKit Cloud** (free tier). Strict-GCP option:
  self-host the LiveKit SFU on GKE/Compute Engine.

---

## Final Bill of Materials

| Component | Technology | Free? | Hosting |
|---|---|---|---|
| Language / runtime | Python 3.12, `livekit-agents` SDK | ✅ OSS | — |
| Orchestration | LiveKit Agents | ✅ OSS | LiveKit Cloud free tier (media) + Cloud Run (worker) |
| LLM | Groq Llama 3.3 70B (fallback: Gemini 2.0 Flash AI Studio) | ✅ Free tier | External free API |
| STT | Groq Whisper large-v3-turbo (fallback: self-hosted `faster-whisper`) | ✅ Free tier | External free API / Cloud Run |
| TTS | Kokoro-82M via kokoro-onnx (fallback: Piper) | ✅ Open weights | In-process in the worker |
| Turn detection / VAD | LiveKit turn-detector + Silero VAD | ✅ Open | in-worker |
| Calendar | Google Calendar API v3 (free) | ✅ Free | Google |
| Time logic | `datetime` + `zoneinfo` + `python-dateutil` | ✅ OSS | in-worker |
| Frontend | Vanilla HTML/CSS/JS + LiveKit JS SDK (served by FastAPI) | ✅ OSS | Cloud Run |
| Secrets | Google Secret Manager | ✅ (free-tier usage) | GCP |
| Observability | LiveKit session logs + structured logging → Cloud Logging | ✅ | GCP |

**Every model in this stack is free.** The only spend is GCP hosting compute.

**Pure-GCP / zero-external variant** (if even free external APIs must be avoided):
self-host `faster-whisper` (STT) + a small open LLM + Kokoro (TTS) all on Cloud
Run. Removes external dependencies entirely at the cost of higher latency and
larger Cloud Run instances.
