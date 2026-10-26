from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .config import TZ
from .http import client
from .models import Event, fingerprint, make_id

CONNECT_LIST = "https://yaleconnect.yale.edu/mobile_ws/v17/mobile_events_list"
CONNECT_ORIGIN = "https://yaleconnect.yale.edu"
TZINFO = ZoneInfo(TZ)


def _row_map(row: dict) -> dict[str, str]:
    fields = [part for part in (row.get("fields") or "").split(",") if part]
    mapped: dict[str, str] = {}
    for index, name in enumerate(fields):
        value = row.get(f"p{index}")
        mapped[name] = "" if value is None else str(value)
    return mapped


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def _parse_dates(html: str) -> tuple[datetime | None, datetime | None]:
    text = unescape(_strip_html(html))
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None, None
    if " - " in text:
        left, right = text.split(" - ", 1)
        try:
            start = dateparser.parse(left, fuzzy=True)
            end = dateparser.parse(right, fuzzy=True, default=start)
            return _aware(start), _aware(end)
        except (ValueError, OverflowError, TypeError):
            pass
    try:
        start = dateparser.parse(text, fuzzy=True)
        return _aware(start), None
    except (ValueError, OverflowError, TypeError):
        return None, None


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZINFO)
    return dt.astimezone(TZINFO)


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.isoformat()


def _tags(html: str) -> str:
    text = _strip_html(html)
    parts = [p.strip() for p in re.split(r"\s{2,}", text) if p.strip()]
    if not parts and text:
        parts = [text]
    # label-tag items often concatenate; split on common glued words is hard, keep compact
    labels = BeautifulSoup(html, "lxml").select(".label-tag")
    if labels:
        return ", ".join(dict.fromkeys(el.get_text(" ", strip=True) for el in labels))
    return ", ".join(parts[:8])


def events_from_rows(
    rows: list,
    source: str = "yale_connect",
    origin: str = CONNECT_ORIGIN,
) -> tuple[list[Event], int]:
    events: list[Event] = []
    found = 0
    for row in rows:
        mapped = _row_map(row)
        if mapped.get("displayType") == "separator" or not mapped.get("eventId"):
            continue
        found += 1
        start_dt, end_dt = _parse_dates(mapped.get("eventDates") or "")
        start = _iso(start_dt)
        if not start:
            continue
        event_id = mapped["eventId"]
        title = unescape(mapped.get("eventName") or "").strip()
        loc = _strip_html(mapped.get("eventLocation") or "")
        path = mapped.get("eventUrl") or f"/rsvp_boot?id={event_id}"
        url = path if path.startswith("http") else origin.rstrip("/") + path
        events.append(
            Event(
                id=make_id(source, event_id, start),
                source=source,
                source_id=event_id,
                title=title,
                start=start,
                end=_iso(end_dt),
                all_day=False,
                location=loc,
                description=_strip_html(mapped.get("ariaEventDetails") or ""),
                url=url,
                host=unescape(mapped.get("clubName") or "").strip(),
                tags=_tags(mapped.get("eventTags") or mapped.get("eventCategory") or ""),
                fingerprint=fingerprint(title, start),
                extra={"club_id": mapped.get("clubId"), "uid": mapped.get("eventUid"), "origin": origin},
            )
        )
    return events, found


def fetch_campusgroups(
    list_url: str,
    origin: str,
    source: str,
    limit: int = 400,
    page_size: int = 50,
) -> list[Event]:
    events: list[Event] = []
    offset = 0
    with client() as http:
        while offset < limit:
            response = http.get(list_url, params={"range": offset, "limit": page_size})
            response.raise_for_status()
            batch, found = events_from_rows(response.json(), source=source, origin=origin)
            events.extend(batch)
            if not found:
                break
            offset += page_size
    return events


def fetch_connect_public(limit: int = 800, page_size: int = 50) -> list[Event]:
    return fetch_campusgroups(CONNECT_LIST, CONNECT_ORIGIN, "yale_connect", limit, page_size)


SOM_LIST = "https://groups.som.yale.edu/mobile_ws/v17/mobile_events_list"
SOM_ORIGIN = "https://groups.som.yale.edu"


def fetch_som_campus_groups(limit: int = 400) -> list[Event]:
    return fetch_campusgroups(SOM_LIST, SOM_ORIGIN, "campus_groups", limit)
