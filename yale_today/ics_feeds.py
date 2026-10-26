from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from icalendar import Calendar
from icalendar import Event as ICalEvent

from .config import TZ
from .http import client
from .models import Event, fingerprint, make_id

TZINFO = ZoneInfo(TZ)

DEFAULT_ICS_SOURCES = [
    ("athletics", "https://yalebulldogs.com/calendar.ashx/calendar.ics"),
    # Residential colleges publish to Google Calendar, not to any Yale
    # system, so none of their events reach the central calendar: a search
    # of the whole database found 0 rows mentioning Benjamin Franklin,
    # Pauli Murray or Timothy Dwight. Each one found gets a line here.
    ("res_college", "https://calendar.google.com/calendar/ical/"
                    "benjaminfranklincollege%40gmail.com/public/basic.ics"),
]


def _to_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.combine(value, datetime.min.time())
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZINFO)
    return dt.astimezone(TZINFO)


def _from_vevent(component: ICalEvent, source: str) -> Event | None:
    start = _to_dt(component.get("dtstart").dt if component.get("dtstart") else None)
    if not start:
        return None
    end_raw = component.get("dtend")
    end = _to_dt(end_raw.dt) if end_raw else None
    uid = str(component.get("uid") or component.get("summary") or start.isoformat())
    title = str(component.get("summary") or "Untitled event").strip()
    loc = str(component.get("location") or "").strip()
    url = str(component.get("url") or "").strip()
    desc = str(component.get("description") or "").strip()
    start_iso = start.isoformat()
    raw_start = component.get("dtstart").dt
    all_day = isinstance(raw_start, date) and not isinstance(raw_start, datetime)
    return Event(
        id=make_id(source, uid, start_iso),
        source=source,
        source_id=uid,
        title=title,
        start=start_iso,
        end=end.isoformat() if end else None,
        all_day=all_day,
        location=loc,
        description=desc,
        url=url,
        host=source.replace("_", " ").title(),
        tags="",
        fingerprint=fingerprint(title, start_iso),
    )


def fetch_ics(url: str, source: str = "ics") -> list[Event]:
    events: list[Event] = []
    with client() as http:
        response = http.get(url)
        response.raise_for_status()
        calendar = Calendar.from_ical(response.content)
    for component in calendar.walk("VEVENT"):
        event = _from_vevent(component, source)
        if event:
            events.append(event)
    return events


def fetch_default_ics() -> list[Event]:
    events: list[Event] = []
    for source, url in DEFAULT_ICS_SOURCES:
        events.extend(fetch_ics(url, source=source))
    return events
