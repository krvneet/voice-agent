"""Deterministic time reasoning for the scheduler.

The LLM never does date arithmetic. It passes *semantic hints* (a natural-language
``day_hint`` such as "late next week" and an optional ``time_of_day`` such as
"afternoon" or "after 7"); this module turns those hints — together with the
current time and timezone — into concrete date ranges, then finds free slots
against the calendar's busy intervals.

Everything here is pure Python (no LiveKit / Google deps) so it is unit-testable
in isolation. This is where the assignment's hard time-parsing cases are solved.
"""

from __future__ import annotations

import calendar as _cal
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# Coarse parts of day (24h). Explicit parts intentionally ignore working hours so
# "evening after 7" can extend past the workday.
_PARTS = {
    "morning": (9.0, 12.0),
    "afternoon": (12.0, 17.0),
    "evening": (17.0, 21.0),
    "night": (19.0, 22.0),
}

_SLOT_GRANULARITY_MIN = 15  # snap candidate starts to this grid


@dataclass
class TimeWindow:
    start: datetime
    end: datetime


@dataclass
class Slot:
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        # e.g. "Tuesday, July 21 at 2:00 PM"
        return self.start.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")

    def to_dict(self) -> dict:
        return {
            "start_iso": self.start.isoformat(),
            "end_iso": self.end.isoformat(),
            "label": self.label,
        }


# ────────────────────────────── helpers ──────────────────────────────

def _tz(tz_name: str) -> ZoneInfo:
    return ZoneInfo(tz_name)


def _float_to_time(x: float) -> time:
    x = max(0.0, min(23.999, x))
    h = int(x)
    m = int(round((x - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    return time(hour=min(h, 23), minute=m)


def _next_weekday(base: date, weekday: int, force_next: bool = False) -> date:
    """Next occurrence of ``weekday`` on/after ``base`` (or strictly after if force_next)."""
    delta = (weekday - base.weekday()) % 7
    if force_next and delta < 7:
        delta = delta + 7 if delta == 0 else delta
        if delta < 7:  # "next" pushes into the following week
            delta += 7
    return base + timedelta(days=delta)


def _last_weekday_of_month(d: date) -> date:
    last_dom = _cal.monthrange(d.year, d.month)[1]
    cur = date(d.year, d.month, last_dom)
    while cur.weekday() >= 5:  # Sat/Sun → walk back to Friday
        cur -= timedelta(days=1)
    return cur


def parse_busy(busy: list[dict], tz_name: str) -> list[tuple[datetime, datetime]]:
    """Convert Calendar freebusy dicts ({"start","end"} RFC3339) to aware tuples."""
    tz = _tz(tz_name)
    out: list[tuple[datetime, datetime]] = []
    for b in busy:
        try:
            s = dateparser.isoparse(b["start"]).astimezone(tz)
            e = dateparser.isoparse(b["end"]).astimezone(tz)
            out.append((s, e))
        except (KeyError, ValueError):
            continue
    return out


# ────────────────────────── day-range resolution ──────────────────────────

def resolve_range(day_hint: str, now: datetime, tz_name: str,
                  default_horizon_days: int = 14) -> TimeWindow:
    """Turn a natural-language day hint into a concrete [start, end] window.

    ``now`` must be timezone-aware. The returned window never starts in the past.
    """
    tz = _tz(tz_name)
    now = now.astimezone(tz)
    today = now.date()
    hint = (day_hint or "").lower().strip()

    def span(d_start: date, d_end: date) -> TimeWindow:
        start_dt = datetime.combine(d_start, time.min, tzinfo=tz)
        end_dt = datetime.combine(d_end, time.max, tzinfo=tz)
        return TimeWindow(max(start_dt, now), end_dt)

    # explicit relative days
    if hint in ("", "any", "anytime", "asap", "soon", "whenever"):
        return span(today, today + timedelta(days=default_horizon_days))
    if "today" in hint:
        return span(today, today)
    if "day after tomorrow" in hint:
        return span(today + timedelta(days=2), today + timedelta(days=2))
    if "tomorrow" in hint:
        return span(today + timedelta(days=1), today + timedelta(days=1))

    # last weekday of month (check before generic "month")
    if "last weekday" in hint or "last working day" in hint or "last business day" in hint:
        ref = today if "next month" not in hint else (_first_of_next_month(today))
        d = _last_weekday_of_month(ref)
        return span(d, d)

    # weekends
    if "weekend" in hint:
        force = "next" in hint
        sat = _next_weekday(today, 5, force_next=force)
        return span(sat, sat + timedelta(days=1))

    # next / this week
    if "next week" in hint:
        nxt_mon = _next_weekday(today, 0, force_next=True)
        if "late" in hint or "end of" in hint:
            return span(nxt_mon + timedelta(days=3), nxt_mon + timedelta(days=6))  # Thu–Sun
        if "early" in hint or "start of" in hint or "beginning" in hint:
            return span(nxt_mon, nxt_mon + timedelta(days=1))  # Mon–Tue
        if "mid" in hint:
            return span(nxt_mon + timedelta(days=1), nxt_mon + timedelta(days=3))  # Tue–Thu
        return span(nxt_mon, nxt_mon + timedelta(days=6))
    if "this week" in hint:
        sunday = today + timedelta(days=(6 - today.weekday()))
        return span(today, sunday)

    # months
    if "next month" in hint:
        first = _first_of_next_month(today)
        last = date(first.year, first.month, _cal.monthrange(first.year, first.month)[1])
        return span(first, last)
    if "this month" in hint:
        last = date(today.year, today.month, _cal.monthrange(today.year, today.month)[1])
        return span(today, last)

    # a named weekday, possibly "next tuesday"
    for name, wd in _WEEKDAYS.items():
        if name in hint:
            d = _next_weekday(today, wd, force_next="next" in hint)
            return span(d, d)

    # explicit date ("June 20", "20th June", "2026-06-20")
    try:
        parsed = dateparser.parse(day_hint, fuzzy=True, default=now)
        d = parsed.date()
        if d < today:  # assume they mean the future occurrence
            try:
                d = d.replace(year=d.year + 1)
            except ValueError:
                pass
        return span(d, d)
    except (ValueError, OverflowError):
        pass

    # fallback: rolling horizon
    return span(today, today + timedelta(days=default_horizon_days))


def _first_of_next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


# ─────────────────────────── time-of-day parsing ───────────────────────────

def time_of_day_hours(time_of_day: str | None, wh_start: int, wh_end: int) -> tuple[float, float]:
    """Return (start_hour, end_hour) floats for a time-of-day hint.

    When no hint is given, defaults to working hours. Explicit hints ("evening",
    "after 7", "before noon") are honoured even beyond working hours.
    """
    if not time_of_day:
        return float(wh_start), float(wh_end)
    t = time_of_day.lower().strip()

    for name, (s, e) in _PARTS.items():
        if name in t:
            return s, e

    # noon / midday phrased with a direction
    if "noon" in t or "midday" in t:
        if "before" in t:
            return float(wh_start), 12.0
        if "after" in t:
            return 12.0, float(wh_end)
        return 12.0, 14.0

    # "after 7", "after 19:00"
    m = re.search(r"after\s+(\d{1,2})(?::(\d{2}))?", t)
    if m:
        h = _coerce_hour(int(m.group(1)), int(m.group(2) or 0), pm_bias=True)
        return h, 22.0
    m = re.search(r"before\s+(\d{1,2})(?::(\d{2}))?", t)
    if m:
        h = _coerce_hour(int(m.group(1)), int(m.group(2) or 0), pm_bias=False)
        return float(wh_start), h

    return float(wh_start), float(wh_end)


def _coerce_hour(h: int, m: int, pm_bias: bool) -> float:
    # bare 1–7 with a PM bias (e.g. "after 7" → 19:00); 8–12 taken literally.
    if pm_bias and 1 <= h <= 7:
        h += 12
    return min(23.99, h + m / 60.0)


# ──────────────────────────── slot searching ────────────────────────────

def _subtract_busy(win_start: datetime, win_end: datetime,
                   busy: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Return free intervals within [win_start, win_end] after removing busy blocks."""
    if win_end <= win_start:
        return []
    clipped = sorted(
        (max(bs, win_start), min(be, win_end))
        for bs, be in busy
        if be > win_start and bs < win_end
    )
    free: list[tuple[datetime, datetime]] = []
    cursor = win_start
    for bs, be in clipped:
        if bs > cursor:
            free.append((cursor, bs))
        cursor = max(cursor, be)
    if cursor < win_end:
        free.append((cursor, win_end))
    return free


def _snap_up(dt: datetime, minutes: int = _SLOT_GRANULARITY_MIN) -> datetime:
    discard = (dt.minute % minutes) * 60 + dt.second
    if discard == 0 and dt.microsecond == 0:
        return dt.replace(microsecond=0)
    return (dt + timedelta(minutes=minutes) - timedelta(seconds=discard)).replace(microsecond=0)


def search_slots(busy: list[tuple[datetime, datetime]], window: TimeWindow,
                 duration_min: int, time_of_day: str | None,
                 wh_start: int, wh_end: int, buffer_min: int = 0,
                 max_results: int = 3) -> list[Slot]:
    """Find up to ``max_results`` free slots that fit duration(+buffer)."""
    tz = window.start.tzinfo
    start_h, end_h = time_of_day_hours(time_of_day, wh_start, wh_end)
    need = timedelta(minutes=duration_min + buffer_min)
    results: list[Slot] = []

    day = window.start.date()
    end_day = window.end.date()
    while day <= end_day and len(results) < max_results:
        day_start = datetime.combine(day, _float_to_time(start_h), tzinfo=tz)
        day_end = datetime.combine(day, _float_to_time(end_h), tzinfo=tz)
        day_start = max(day_start, window.start)
        day_end = min(day_end, window.end)

        for free_start, free_end in _subtract_busy(day_start, day_end, busy):
            cursor = _snap_up(free_start)
            while cursor + need <= free_end and len(results) < max_results:
                results.append(Slot(cursor, cursor + timedelta(minutes=duration_min)))
                cursor += need  # non-overlapping distinct options
        day += timedelta(days=1)
    return results


def find_slots(busy: list[tuple[datetime, datetime]], day_hint: str,
               time_of_day: str | None, duration_min: int, now: datetime,
               tz_name: str, wh_start: int, wh_end: int,
               buffer_min: int = 0, max_results: int = 3) -> list[Slot]:
    window = resolve_range(day_hint, now, tz_name)
    return search_slots(busy, window, duration_min, time_of_day,
                        wh_start, wh_end, buffer_min, max_results)


def find_alternatives(busy: list[tuple[datetime, datetime]], day_hint: str,
                      time_of_day: str | None, duration_min: int, now: datetime,
                      tz_name: str, wh_start: int, wh_end: int,
                      buffer_min: int = 0, max_results: int = 3) -> list[Slot]:
    """Graceful conflict resolution: widen the search when the ask is fully booked.

    Drops the time-of-day constraint and extends the horizon a week beyond the
    originally requested window.
    """
    window = resolve_range(day_hint, now, tz_name)
    widened = TimeWindow(window.start, window.end + timedelta(days=7))
    return search_slots(busy, widened, duration_min, None,
                        wh_start, wh_end, buffer_min, max_results)
