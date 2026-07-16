"""The scheduler Agent: system prompt + the three calendar tools.

The Agent holds per-call session memory (remembered duration, the slots it last
offered, and any reference event) so the LLM never has to re-ask. Date math lives
in ``time_resolver``; calendar I/O lives in ``calendar_client``. This class wires
them to the LLM via ``@function_tool`` methods.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from livekit.agents import Agent, RunContext, function_tool

import time_resolver as tr
from calendar_client import CalendarClient, CalendarError, event_start

logger = logging.getLogger("scheduler-agent")


def build_instructions(now: datetime, tz_name: str, wh_start: int, wh_end: int) -> str:
    return f"""You are a friendly, concise voice assistant that helps the user schedule ONE meeting on their calendar.

CONTEXT
- The current date and time is {now.strftime('%A, %B %d, %Y, %I:%M %p')} ({tz_name}).
- Working hours are {wh_start:02d}:00 to {wh_end:02d}:00, Monday to Friday.

WHAT TO COLLECT
- The meeting DURATION (in minutes), a preferred DAY, and a preferred TIME of day.
- If something required is missing and cannot be reasonably inferred, ask ONE short clarifying question.
- A "quick chat" ~15 min, a "sync"/"sync-up" ~30 min, a "meeting" ~30-60 min if unspecified — confirm the duration you assume.

HOW TO ACT
- Never invent availability. To find times, call `find_availability`.
- To resolve a request relative to an existing event (e.g. "a day after Project Alpha Kick-off"), call `find_event` FIRST, then use its date.
- Do NOT do date arithmetic yourself. Pass natural-language hints to the tools:
  - day_hint examples: "tuesday", "next week", "late next week", "last weekday of this month", "June 20th".
  - time_of_day examples: "morning", "afternoon", "evening", "after 7", "before noon".
- When the requested window is fully booked, the tool returns alternatives — proactively offer them ("Tuesday afternoon is full; Wednesday morning has 10 or 11 — would either work?").
- Remember everything already said (duration, day, preferences). If the user changes a requirement mid-conversation (e.g. 30 → 60 minutes), re-run `find_availability` with the new value but keep the other preferences.
- Before booking, read back the concrete slot and get a clear yes, then call `book_meeting` using the exact start_iso from the slot you offered.

STYLE
- Keep replies to 1-2 short spoken sentences. No lists, no markdown, no emojis. Speak times naturally ("two thirty PM", not "14:30").
"""


class SchedulerAgent(Agent):
    def __init__(self, *, calendar: CalendarClient, now: datetime, tz_name: str,
                 wh_start: int, wh_end: int):
        super().__init__(instructions=build_instructions(now, tz_name, wh_start, wh_end))
        self._cal = calendar
        self._now = now
        self._tz = tz_name
        self._wh_start = wh_start
        self._wh_end = wh_end
        # per-call memory
        self._duration_min: int | None = None
        self._last_offered: list[dict] = []

    # ── internal helpers ────────────────────────────────────────────────
    def _busy_window(self, day_hint: str) -> tuple[str, str, tr.TimeWindow]:
        """Resolve the day hint and return (timeMin, timeMax, window) for freebusy.

        timeMax is widened by a week so conflict alternatives are covered by the
        same single freebusy query.
        """
        window = tr.resolve_range(day_hint, self._now, self._tz)
        time_min = window.start.isoformat()
        time_max = (window.end + timedelta(days=8)).isoformat()
        return time_min, time_max, window

    # ── tools ───────────────────────────────────────────────────────────
    @function_tool
    async def find_availability(
        self,
        context: RunContext,
        duration_minutes: int,
        day_hint: str,
        time_of_day: str | None = None,
        buffer_minutes: int = 0,
    ) -> dict:
        """Find available meeting slots on the calendar.

        Args:
            duration_minutes: Meeting length in minutes (e.g. 30, 60).
            day_hint: Natural-language day preference, e.g. "tuesday", "next week",
                "late next week", "last weekday of this month", "June 20th".
            time_of_day: Optional time preference, e.g. "morning", "afternoon",
                "evening", "after 7", "before noon".
            buffer_minutes: Optional free buffer to leave before the slot (e.g. 60
                to "decompress" after a previous meeting).
        """
        self._duration_min = duration_minutes
        try:
            time_min, time_max, _ = self._busy_window(day_hint)
            busy = tr.parse_busy(self._cal.get_busy(time_min, time_max), self._tz)
        except CalendarError as e:
            logger.error("calendar error: %s", e)
            return {"status": "error", "message": "I couldn't reach the calendar just now."}

        slots = tr.find_slots(busy, day_hint, time_of_day, duration_minutes,
                              self._now, self._tz, self._wh_start, self._wh_end,
                              buffer_minutes)
        if slots:
            self._last_offered = [s.to_dict() for s in slots]
            return {"status": "available", "slots": self._last_offered}

        alts = tr.find_alternatives(busy, day_hint, time_of_day, duration_minutes,
                                    self._now, self._tz, self._wh_start, self._wh_end,
                                    buffer_minutes)
        self._last_offered = [s.to_dict() for s in alts]
        return {
            "status": "no_slots_in_window",
            "message": "The requested time is fully booked.",
            "alternatives": self._last_offered,
        }

    @function_tool
    async def find_event(self, context: RunContext, query: str) -> dict:
        """Find an existing calendar event by name to anchor a relative request.

        Args:
            query: Free-text name of the event, e.g. "Project Alpha Kick-off".
        """
        time_min = self._now.isoformat()
        time_max = (self._now + timedelta(days=60)).isoformat()
        event = self._cal.find_event(query, time_min, time_max)
        if not event:
            return {"status": "not_found", "query": query}
        start = event_start(event)
        return {
            "status": "found",
            "summary": event.get("summary"),
            "start_iso": start.isoformat() if start else None,
            "date": start.strftime("%A, %B %d") if start else None,
        }

    @function_tool
    async def book_meeting(
        self,
        context: RunContext,
        start_iso: str,
        duration_minutes: int | None = None,
        title: str = "Meeting",
    ) -> dict:
        """Book the meeting after the user confirms a specific slot.

        Args:
            start_iso: The exact ISO start time of the chosen slot (from a slot
                previously offered by find_availability).
            duration_minutes: Meeting length; defaults to the remembered duration.
            title: Short meeting title.
        """
        from dateutil import parser as dateparser

        dur = duration_minutes or self._duration_min or 30
        try:
            start = dateparser.isoparse(start_iso)
        except ValueError:
            return {"status": "error", "message": "That start time didn't parse."}
        end = start + timedelta(minutes=dur)
        try:
            result = self._cal.create_event(start.isoformat(), end.isoformat(), title=title)
        except Exception as e:  # noqa: BLE001 — surface any API failure to the agent
            logger.error("booking failed: %s", e)
            return {"status": "error", "message": "I couldn't create the event."}
        return {
            "status": "booked",
            "when": start.strftime("%A, %B %d at %I:%M %p").replace(" 0", " "),
            "duration_minutes": dur,
            "link": result.get("htmlLink"),
        }
