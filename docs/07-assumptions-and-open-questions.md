# 07 — Assumptions & Open Questions

The "communication" file: decisions taken by default so implementation isn't
blocked, plus the handful of things worth confirming. Nothing here blocks
starting — defaults are chosen and defensible.

---

## 1. Assumptions taken (proceeding on these unless told otherwise)

| # | Assumption | Impact if wrong |
|---|---|---|
| A0 | **Locked constraints:** free models only; **GCP = hosting only** (no paid GCP AI). | Defines the whole model layer. |
| A1 | Voice orchestration = **LiveKit Agents on LiveKit Cloud** (free tier, media), agent worker on GCP Cloud Run. | Whole architecture; changing this is a rework. |
| A2 | Cascade pipeline (Whisper + Llama/Gemini + Kokoro), not realtime speech-to-speech. | Swappable via LiveKit plugin config. |
| A3 | LLM = **Groq Llama 3.3 70B (free)**; fallback **Gemini 2.0 Flash via AI Studio (free)**. | One-line plugin swap either way. |
| A4 | Calendar auth = **service account + shared demo calendar** (not real end-user OAuth). | OAuth path documented; adds a consent flow if required. |
| A5 | **Single demo calendar**, single timezone from env (e.g. `Asia/Kolkata`), working hours 09:00–18:00. | UI/multi-user would be added work. |
| A6 | POC scale: one warm worker (Kokoro TTS in-process, 2 vCPU); no HA/autoscaling; in-memory session state. | Fine for demo; not production. |
| A7 | STT = **Groq Whisper (free API)**; TTS = **Kokoro/Piper self-hosted on Cloud Run (free)**. | Free-tier rate limits apply to Groq; self-hosted `faster-whisper` is the pure fallback. |
| A8 | Free external APIs (Groq / Gemini AI Studio) are acceptable, since GCP is for hosting only. | If *zero* external deps are required, use the fully self-hosted pure-GCP variant (higher latency, bigger instances). |
| A9 | Public access via Cloud Run HTTPS URL is sufficient (no custom domain required). | Custom domain is a small add-on. |
| A10 | It is a **session-aware voice-to-voice conversational agent** — remembers context across turns within a call; no cross-call persistence. | Cross-call memory = add a small DB (out of POC scope). |

## 2. Open questions worth confirming

These change *scope/polish*, not the core stack — safe to start while these
settle.

1. **Are free external APIs OK, or must everything be self-hosted on GCP?**
   Groq/Gemini-AI-Studio are free but external. *(Default: free external APIs
   allowed — GCP is hosting-only. Fully self-hosted pure-GCP variant is ready if
   "zero external deps" is required, at a latency cost.)*
2. **Real user calendar or demo calendar?** Must the agent book on the
   *submitter's own* Google Calendar (→ OAuth), or is a dedicated demo calendar
   fine for the recording? *(Default: demo calendar.)*
3. **Timezone** for the demo. *(Default: `Asia/Kolkata`; trivially configurable.)*
4. **Kokoro vs Piper for TTS?** Kokoro = better quality; Piper = lower latency on
   CPU. *(Default: start with Kokoro, fall back to Piper if the latency budget is
   tight during the demo.)*
5. **Keep it running or tear down after the demo?** The warm worker is the
   main cost. *(Default: keep warm through the submission window, then tear down /
   set `min-instances=0`.)*

## 3. Bonus / "above and beyond" ideas (from the assignment's bonus section)

Candidates to differentiate the submission, in rough effort order:

- **"Let me check…" filler speech** to mask calendar-API latency → feels faster
  than 800ms.
- **Read-back confirmation** before booking → trust + correctness.
- **Barge-in / interruption** handling (comes free with LiveKit) → natural feel.
- **Two-step relative reasoning** ("after Project Alpha Kick-off") demonstrated
  live → shows real agentic tool chaining.
- **Deterministic text-mode test suite** over all hard scenarios → proves
  robustness in the README without re-recording audio.
- **Dual pipeline toggle** (cascade ↔ realtime) behind an env flag → shows depth.
- **Timezone-aware, working-hours-aware** slotting → production sensibility.

## 4. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Latency over 800ms (in-process TTS is the pinch point) | Piper instead of Kokoro; `--cpu=2` + warm worker; filler speech on calendar turns. |
| Free-tier rate limits (Groq RPM/RPD) hit mid-demo | Single-user demo stays within limits; Gemini-AI-Studio fallback; self-hosted `faster-whisper` for STT. |
| LLM hallucinates dates | Date math in Python resolver, not the LLM; inject `now` every turn. |
| Cold-start pause during demo | `min-instances=1`, `--no-cpu-throttling` on worker + TTS. |
| Free-tier data-use / privacy | Demo calendar only, no real PII; noted in README. |
| Calendar auth misconfig | Verify service-account share + a scripted `freebusy.query` smoke test before recording. |

## 5. What I need from you to lock the plan

The two hard constraints (free models, GCP-hosting-only) are now baked in.
Confirm (or override) the defaults in **§2 questions 1, 2, and 3** — free-external
vs fully-self-hosted, demo vs real calendar, and timezone. Everything else in
[02-tech-stack.md](02-tech-stack.md) is ready to implement as-is.
