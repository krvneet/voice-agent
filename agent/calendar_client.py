"""Thin, typed wrapper over the Google Calendar API v3.

Authenticates with a service-account key (the ``scheduler-cal`` SA) that has been
shared into the demo calendar. Exposes only the three operations the agent needs:
read busy intervals, search for a named event, and create a meeting.
"""

from __future__ import annotations

import logging
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger("calendar")

# Write scope covers freebusy + list + insert.
SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarError(RuntimeError):
    """Raised when the Calendar API reports an access/quota problem."""


class CalendarClient:
    def __init__(self, credentials_path: str, calendar_id: str, timezone: str):
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        # cache_discovery=False avoids noisy warnings and file-cache writes on Cloud Run.
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self._calendar_id = calendar_id
        self._tz = timezone

    # ── read: busy intervals ───────────────────────────────────────────
    def get_busy(self, time_min: str, time_max: str) -> list[dict]:
        """Return busy intervals ([{"start","end"}]) in the window (RFC3339 in/out)."""
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "timeZone": self._tz,
            "items": [{"id": self._calendar_id}],
        }
        resp = self._service.freebusy().query(body=body).execute()
        cal = resp["calendars"][self._calendar_id]
        if cal.get("errors"):
            raise CalendarError(
                f"Calendar freebusy errors: {cal['errors']} — is the calendar "
                f"shared with the service account?"
            )
        return cal.get("busy", [])

    # ── read: find a named event ────────────────────────────────────────
    def find_event(self, query: str, time_min: str, time_max: str) -> dict | None:
        """Return the first event matching a free-text query, or None."""
        resp = (
            self._service.events()
            .list(
                calendarId=self._calendar_id,
                q=query,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=5,
            )
            .execute()
        )
        items = resp.get("items", [])
        return items[0] if items else None

    # ── write: create a meeting ─────────────────────────────────────────
    def create_event(self, start_iso: str, end_iso: str, title: str = "Meeting",
                     description: str = "Booked by the Smart Scheduler voice agent") -> dict:
        """Insert a timed event; returns {"id", "htmlLink", "start"}."""
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": self._tz},
            "end": {"dateTime": end_iso, "timeZone": self._tz},
        }
        created = (
            self._service.events()
            .insert(calendarId=self._calendar_id, body=event)
            .execute()
        )
        return {
            "id": created.get("id"),
            "htmlLink": created.get("htmlLink"),
            "start": created.get("start", {}).get("dateTime"),
        }


def event_start(event: dict) -> datetime | None:
    """Extract an event's start datetime (timed events only)."""
    from dateutil import parser as dateparser

    dt = event.get("start", {}).get("dateTime")
    if not dt:
        return None
    try:
        return dateparser.isoparse(dt)
    except ValueError:
        return None
