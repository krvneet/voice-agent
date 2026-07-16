# 06 — Agent & Conversation Design

The "brain" logic: prompting strategy, state, tool-calling flow, and how each
hard time-parsing / conflict scenario is handled. This is where the evaluation
criteria (agentic logic, prompt engineering) are won.

---

## 1. Prompting strategy

A single structured **system prompt** defines role, behavior, and hard rules,
plus **tool schemas** (from [05](05-calendar-integration.md)). The prompt is
short and directive — long prompts hurt latency and add drift.

### System prompt skeleton

```
You are a friendly, concise voice scheduling assistant.
CONTEXT: Current datetime is {now_iso} ({timezone}). Working hours 09:00–18:00.
GOAL: Help the user book ONE meeting on the calendar.

RULES:
- Collect: meeting DURATION, preferred DAY, preferred TIME. If any is missing
  and cannot be reasonably inferred, ask ONE short clarifying question.
- Never invent availability. To learn availability, call find_slots.
- To resolve a request relative to a named event, call find_event first.
- Do NOT do date math yourself; pass semantic hints to the tools.
- When a window is full, proactively suggest the nearest alternatives.
- Confirm the final slot before calling book_meeting.
- Keep replies to 1–2 short spoken sentences. No lists, no markdown.
- Remember everything the user already told you; don't re-ask.
```

### Why these rules

- "One clarifying question" → matches F2 without interrogating the user.
- "Never invent availability / call find_slots" → forces grounded tool use
  (evaluation: correct API usage).
- "Don't do date math" → offloads the unreliable part to deterministic code.
- "1–2 short sentences" → natural spoken cadence + lower TTS latency.

## 2. Conversation state machine (conceptual)

```
        ┌─────────────┐   missing info    ┌──────────────────┐
  ─────▶│  GATHERING  │──────────────────▶│  CLARIFYING (ask)│
        └──────┬──────┘◀───── answer ─────└──────────────────┘
               │ enough info
               ▼
        ┌─────────────┐  full window   ┌────────────────────┐
        │  SEARCHING  │───────────────▶│  RESOLVING CONFLICT │
        │ (find_slots)│◀── new prefs ──│ (offer alternatives)│
        └──────┬──────┘                └────────────────────┘
               │ slot chosen + confirmed
               ▼
        ┌─────────────┐
        │   BOOKING   │  (book_meeting) → confirmation
        └─────────────┘
```

State is not hard-coded as a rigid FSM — the LLM drives transitions, guided by
the prompt, while the explicit `SessionState` object (see [03 §5](03-architecture.md))
holds the remembered facts so nothing is re-asked. Requirement changes (F9) just
mutate a field and loop back to SEARCHING.

## 3. The time-parsing pipeline (the hard part)

**Split of responsibility:**

| Layer | Does |
|---|---|
| **LLM** | Understands fuzzy language; emits *semantic* hints + decides tool + whether to ask. |
| **Python resolver** | Converts hints + `now` + reference events → concrete UTC/tz date ranges. |
| **Calendar** | Ground truth for busy/free and named events. |

### Scenario → mechanism

| Request | Flow |
|---|---|
| "Tuesday afternoon, 1 hour" | LLM → `find_slots(duration=60, day_hint="next tuesday", time_of_day="afternoon")` → resolver maps "afternoon"→12:00–17:00 on the next Tuesday. |
| "sometime late next week" | Resolver computes next week's Thu–Fri from `now`; LLM may confirm duration. |
| "45 min before my flight Friday 6 PM" | LLM sets a **deadline**: `find_slots(duration=45, date_range_end=Fri 18:00)`, resolver searches the latest fitting slot *before* 18:00. |
| "a day or two after 'Project Alpha Kick-off'" | LLM calls `find_event("Project Alpha Kick-off")` → gets its date → then `find_slots` for date+1..date+2. **Two-step tool use.** |
| "last weekday of this month" | Resolver computes the last Mon–Fri of the current month from `now`. |
| "next week, not too early, not Wednesday" | LLM extracts negatives → resolver excludes Wednesday + before ~10:00; if still vague, LLM asks one question. |
| "our usual sync-up" | Default duration (30 min) from config/session memory; LLM confirms. |
| "evening after 7, but 1h to decompress after last meeting" | LLM reads last event end via `find_event`/`events.list`, sets `buffer_minutes=60`, `time_of_day` ≥ max(19:00, last_end+60). |
| Duration 30→60 mid-flow | Update `SessionState.duration_minutes`; re-run `find_slots` with same day/time preference. |

### "Speak a filler while resolving"

For turns that hit the calendar, the agent emits a brief acknowledgement
("Let me check Tuesday for you…") *before* the tool result returns, keeping
perceived latency under the 800ms feel even when the API round-trip pushes real
latency higher.

## 4. Conflict resolution logic (F7)

`find_slots` returns `{slots: [...], alternatives: [...]}`. When `slots` is empty
the prompt instructs the agent to *offer* the nearest alternatives rather than
dead-end:

> "Tuesday afternoon is fully booked. Wednesday morning has 10:00 or 11:30 —
> would either work?"

The resolver produces alternatives by widening the search window in a sensible
order: same day other time → adjacent days same time-of-day → next available.

## 5. Confirmation & booking

Before `book_meeting`, the agent read-backs the concrete slot for confirmation
("So that's a 1-hour meeting Wednesday at 10:00 AM — shall I book it?"). Only on
a clear yes does it call `book_meeting`, then confirms with the result.

## 6. Testing the design

A scripted test suite (text-mode, bypassing voice) drives each [01 §3](01-requirements-analysis.md)
scenario against a seeded calendar and asserts the correct tool calls + resolved
ranges. This validates agentic logic deterministically without re-recording
audio every time — and doubles as evidence of correctness in the README.
