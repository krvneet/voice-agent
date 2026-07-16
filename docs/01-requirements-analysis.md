# 01 — Requirements Analysis

Decomposition of the NxD "Smart Scheduler AI Agent" assignment into concrete,
testable engineering requirements. This is the source of truth the stack in
[02-tech-stack.md](02-tech-stack.md) must satisfy.

---

## 1. Functional requirements

| ID | Requirement | Notes |
|---|---|---|
| F1 | Multi-turn, stateful conversation | Agent must remember facts (duration, day, preferences) across turns. |
| F2 | Ask clarifying questions | When required info (duration, day, time) is missing, ask — don't guess. |
| F3 | Voice in / voice out | User speaks; agent responds with synthesized speech. Text is not the primary interface. |
| F4 | Google Calendar read | Query free/busy and existing events to find available slots. |
| F5 | Google Calendar write | Create the chosen meeting event. |
| F6 | Slot proposal | Offer concrete available times ("2:00 PM or 4:30 PM"). |
| F7 | Conflict resolution | When the requested window is full, proactively suggest alternatives. |
| F8 | Smart time parsing | Handle relative/contextual/vague time expressions (see §3). |
| F9 | Mid-conversation requirement changes | Re-run search when constraints change (e.g. duration 30m→60m) while retaining other context. |

## 2. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| N1 | **Latency** | <800ms from end-of-user-speech to start-of-agent-speech. |
| N2 | **Naturalness** | Streaming TTS, barge-in/interruption support, no robotic pauses. |
| N3 | **Deployed & public** | Running in the cloud (GCP preferred), reachable via a public URL. |
| N4 | **Reproducible** | README with step-by-step setup; public repo. |
| N5 | **Observability** | Enough logging/tracing to debug latency and tool calls. |

## 3. Time-parsing scenarios the agent must handle

Sourced directly from the assignment's "Testing Cases". Each is mapped to the
mechanism that solves it — detail in [06-agent-conversation-design.md](06-agent-conversation-design.md).

| Scenario | Mechanism |
|---|---|
| "Tuesday afternoon", "morning of June 20th" | LLM → structured `{day, part_of_day}` → resolver maps to time ranges. |
| "sometime late next week" | LLM → relative window; resolver computes date range from *current date*. |
| "45 min before my flight Friday 6 PM" | Deadline reasoning: resolver searches backward from a hard end time. |
| "a day or two after the 'Project Alpha Kick-off' event" | **Two-step tool use**: first `find_event(name)` → get its date → then search relative to it. |
| "last weekday of this month" | Pure date logic in the resolver (calendar math). |
| "next week, not too early, not Wednesday" | LLM extracts negative constraints; may require one clarifying question. |
| "our usual sync-up" (implied 30 min) | Default/remembered duration in session state or config. |
| "evening after 7, but 1h to decompress after last meeting" | Dynamic buffer: read last event end time, add buffer, then search. |
| Duration change mid-flow (30m → 60m) | Update one slot in session state, re-run `find_slots`, keep day/time preference. |

**Key design consequence:** the LLM should *not* do date arithmetic itself
(it's unreliable). It extracts **structured constraints**; deterministic Python
does the math against the calendar. The current date/time and timezone are
injected into the LLM context every turn.

## 4. Evaluation criteria → design response

| Evaluated for | How the stack/design addresses it |
|---|---|
| Agentic logic & context memory | LiveKit `AgentSession` chat context + explicit session state object. |
| Prompt engineering | Structured system prompt + tool schemas; see doc 06. |
| API integration quality | Typed Calendar tool functions, service-account auth, error handling. |
| Voice + latency <800ms | LiveKit pipeline, streaming STT/TTS, fast Flash-tier LLM; budget in doc 03. |
| Conflict resolution | `find_slots` returns alternatives; prompt instructs proactive suggestions. |
| Time parsing | Constraint-extraction + Python resolver (§3). |

## 5. Explicitly out of scope for the POC

- Multi-user auth / accounts (single demo calendar).
- Timezone selection UI (fixed demo timezone, configurable via env).
- Recurring meetings, attendee invitations beyond the calendar owner.
- Production-grade horizontal autoscaling / HA (single warm instance is fine).
- Persistent conversation history across sessions (in-memory per call is fine).
