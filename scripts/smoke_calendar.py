"""Calendar smoke test — verifies the service-account share works.

Run after GCP setup (docs/08) and before the demo:
    python scripts/smoke_calendar.py

Reads today's busy intervals on the configured demo calendar. If the calendar
isn't shared with the service account, CalendarClient raises a clear error.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from calendar_client import CalendarClient  #noqa: E402
from config import get_settings  #noqa: E402


def main() -> int:
    s = get_settings()
    if not s.calendar_id:
        print("GCAL_CALENDAR_ID is not set — check your .env")
        return 1

    tz = ZoneInfo(s.timezone)
    now = datetime.now(tz)
    time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    time_max = (now + timedelta(days=1)).isoformat()

    client = CalendarClient(s.google_credentials_path, s.calendar_id, s.timezone)
    busy = client.get_busy(time_min, time_max)

    print(f"Calendar: {s.calendar_id}")
    print(f"Window:   {time_min} .. {time_max}")
    if busy:
        print(f"Busy intervals today ({len(busy)}):")
        for b in busy:
            print(f"  {b['start']} → {b['end']}")
    else:
        print("No busy intervals today (calendar reachable and empty).")
    print("\n✅ Service account can read the calendar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
