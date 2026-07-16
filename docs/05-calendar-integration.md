# 05 — Google Calendar Integration

Auth model, API surface, and the tool functions the agent exposes to the LLM.

---

## 1. Auth model — service account (POC)

**Chosen:** a dedicated **service account** + a **demo calendar** shared with
that service account's email. This is headless — no per-session OAuth consent —
which is exactly right for a voice agent booking against a fixed demo calendar.

### Setup

1. In the GCP project, create a service account, e.g.
   `scheduler-agent@PROJECT.iam.gserviceaccount.com`. Download its JSON key
   (stored in Secret Manager, never in the repo).
2. Enable the **Google Calendar API** (`calendar-json.googleapis.com`).
3. Create (or pick) a Google Calendar to act as the demo calendar. In its
   *Settings → Share with specific people*, add the service-account email with
   **"Make changes to events"** permission.
4. Note the calendar ID (looks like `...@group.calendar.google.com` or the demo
   account's primary address) → env var `GCAL_CALENDAR_ID`.

> **Why sharing works:** a service account has no calendar of its own that you
> can see in the UI. Sharing a normal calendar *to* the service account lets it
> read/write that calendar's events with no interactive consent.

### Scopes

`https://www.googleapis.com/auth/calendar` (read + write events). If only
read+book on one calendar is needed, `.../auth/calendar.events` is sufficient.

## 2. Alternative — OAuth 2.0 (real end-user calendar)

If the agent must touch a *real user's personal* calendar instead of a demo one:

- Use the **Authorization Code flow** with a consent screen; store the refresh
  token securely (Secret Manager / encrypted store).
- Adds a one-time browser consent step and token-refresh handling.
- Documented as the production path; **not used for the POC** to avoid the
  consent dance during a voice demo.

Domain-wide delegation (Workspace admin impersonation) is explicitly out of scope.

## 3. API surface used

| Operation | Calendar API call | Purpose |
|---|---|---|
| Find busy windows | `freebusy.query` | Fast way to get busy blocks in a date range → compute free slots. |
| List events | `events.list` (timeMin/timeMax, `q=` search) | Find a named reference event ("Project Alpha Kick-off"); inspect last meeting of the day. |
| Create meeting | `events.insert` | Book the chosen slot (F5). |
| (optional) Update | `events.patch` | Reschedule if extended later. |

`freebusy.query` is preferred for slot-finding: one call returns all busy
intervals in the window, and free slots are the gaps between them (intersected
with the user's time preference and working hours).

## 4. Tool functions exposed to the LLM

These are the Python functions registered as LiveKit **function tools** (called
by the LLM — Groq Llama or Gemini AI Studio).
The LLM decides *when* to call them and supplies structured arguments; the
functions do deterministic date math + Calendar API calls.

```python
find_slots(
    duration_minutes: int,
    date_range_start: str,   # ISO date, resolved by caller from constraints
    date_range_end: str,
    time_of_day: str | None, # "morning"|"afternoon"|"evening"|explicit range
    buffer_minutes: int = 0, # e.g. "1h to decompress"
) -> list[Slot]              # available slots + nearest alternatives if empty

find_event(
    query: str,              # "Project Alpha Kick-off"
    date_range_start: str | None,
    date_range_end: str | None,
) -> Event | None            # so the agent can anchor relative requests

book_meeting(
    start_iso: str,
    duration_minutes: int,
    title: str = "Meeting",
) -> BookingResult           # confirmation with event link
```

### Design notes

- **The LLM does not compute dates.** It passes semantic hints
  (`time_of_day="afternoon"`, or a resolved range). A Python **resolver** turns
  fuzzy expressions + *current datetime* + reference events into concrete
  `date_range_start/end`. See [06](06-agent-conversation-design.md).
- `find_slots` **always returns alternatives** when the requested window is full,
  enabling graceful conflict resolution (F7) without an extra round-trip.
- Working-hours bounds (e.g. 09:00–18:00) and timezone come from config so slots
  are sensible.
- All datetimes are timezone-aware (`zoneinfo`, `AGENT_TIMEZONE`).

## 5. Verification for the demo

Pre-seed the demo calendar with a few events (a busy Tuesday afternoon, a
"Project Alpha Kick-off", a late-day meeting) so the conflict-resolution and
relative-time scenarios from [01 §3](01-requirements-analysis.md) actually
trigger during the recording.
