"""Text-mode tests for the deterministic time logic.

These exercise the assignment's hard time-parsing + conflict-resolution cases
without needing voice or a live calendar — fast, deterministic proof that the
agentic logic is correct. Run: `pytest tests/ -v`
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

import time_resolver as tr  # noqa: E402

TZ = "Asia/Kolkata"
# Fixed reference: Thursday, 16 July 2026, 10:00
NOW = datetime(2026, 7, 16, 10, 0, tzinfo=ZoneInfo(TZ))


def _d(win):
    return win.start.date().isoformat(), win.end.date().isoformat()


# ─────────────────────────── day-range resolution ───────────────────────────

def test_today_tomorrow():
    assert _d(tr.resolve_range("today", NOW, TZ)) == ("2026-07-16", "2026-07-16")
    assert _d(tr.resolve_range("tomorrow", NOW, TZ)) == ("2026-07-17", "2026-07-17")


def test_named_weekday():
    # next upcoming Tuesday after Thu 16 → 21 July
    assert _d(tr.resolve_range("tuesday", NOW, TZ)) == ("2026-07-21", "2026-07-21")


def test_late_next_week():
    s, e = _d(tr.resolve_range("late next week", NOW, TZ))
    assert (s, e) == ("2026-07-30", "2026-08-02")  # Thu–Sun of next week


def test_last_weekday_of_month():
    # 31 July 2026 is a Friday → the last weekday
    assert _d(tr.resolve_range("last weekday of this month", NOW, TZ)) == (
        "2026-07-31", "2026-07-31",
    )


def test_explicit_future_date_rolls_forward():
    # June 20 already passed in 2026 → assume next occurrence (2027)
    s, _ = _d(tr.resolve_range("the morning of June 20th", NOW, TZ))
    assert s == "2027-06-20"


# ─────────────────────────── time-of-day parsing ───────────────────────────

def test_parts_of_day():
    assert tr.time_of_day_hours("morning", 9, 18) == (9.0, 12.0)
    assert tr.time_of_day_hours("afternoon", 9, 18) == (12.0, 17.0)
    assert tr.time_of_day_hours("evening", 9, 18) == (17.0, 21.0)


def test_relative_hours():
    assert tr.time_of_day_hours("after 7", 9, 18) == (19.0, 22.0)  # PM bias
    assert tr.time_of_day_hours("before noon", 9, 18) == (9.0, 12.0)
    assert tr.time_of_day_hours("after 19:00", 9, 18) == (19.0, 22.0)


# ─────────────────────────── slots + conflict resolution ───────────────────

def _busy(*pairs):
    raw = [{"start": s, "end": e} for s, e in pairs]
    return tr.parse_busy(raw, TZ)


def test_afternoon_booked_then_alternatives():
    busy = _busy(("2026-07-21T12:00:00+05:30", "2026-07-21T17:00:00+05:30"))
    slots = tr.find_slots(busy, "tuesday", "afternoon", 60, NOW, TZ, 9, 18)
    assert slots == []  # fully booked
    alts = tr.find_alternatives(busy, "tuesday", "afternoon", 60, NOW, TZ, 9, 18)
    assert alts, "expected fallback alternatives"
    assert all(s.start.hour < 12 for s in alts)  # morning of same day is free


def test_slots_fit_within_deadline():
    # "45 min before Friday 6 PM" → Friday 24 July, before 18:00
    busy = _busy()
    slots = tr.find_slots(busy, "friday", "before 18:00", 45, NOW, TZ, 9, 18)
    assert slots
    assert all(s.end.hour <= 18 and s.end.minute == 0 or s.end.hour < 18 for s in slots)
    assert all(s.end.hour <= 18 for s in slots)


def test_duration_change_reuses_day_preference():
    busy = _busy()
    thirty = tr.find_slots(busy, "tuesday", "morning", 30, NOW, TZ, 9, 18)
    sixty = tr.find_slots(busy, "tuesday", "morning", 60, NOW, TZ, 9, 18)
    assert thirty and sixty
    # same day retained across a duration change
    assert thirty[0].start.date() == sixty[0].start.date() == datetime(2026, 7, 21, tzinfo=ZoneInfo(TZ)).date()
    assert (sixty[0].end - sixty[0].start).seconds == 3600


def test_evening_buffer_after_last_meeting():
    # last meeting ends 18:00; want evening after 7 with 60-min decompress buffer
    busy = _busy(("2026-07-21T16:00:00+05:30", "2026-07-21T18:00:00+05:30"))
    slots = tr.find_slots(busy, "tuesday", "after 7", 30, NOW, TZ, 9, 21, buffer_min=60)
    assert slots
    assert all(s.start.hour >= 19 for s in slots)
