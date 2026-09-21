from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

from .config import TZ
from .http import client
from .models import Event, fingerprint, make_id

TZINFO = ZoneInfo(TZ)

NHFPL_CALS = "21963,20141,20143,20135,20144,20145"
NHFPL_LIST = "https://nhfpl.libcal.com/ajax/calendar/list"
UNH_LOCALIST = "https://events.newhaven.edu/api/2/events"


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZINFO)
    return dt.astimezone(TZINFO)


def fetch_nhfpl(months: int = 2) -> list[Event]:
    events: list[Event] = []
    today = datetime.now(TZINFO)
    with client() as http:
        for offset in range(months):
            month = today.month + offset
            year = today.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            response = http.get(NHFPL_LIST, params={"c": NHFPL_CALS, "month": month, "year": year})
            response.raise_for_status()
            payload = response.json()
            for row in payload.get("results") or []:
                start_raw = row.get("startdt") or ""
                try:
                    start = _aware(dateparser.parse(start_raw))
                except (ValueError, TypeError, OverflowError):
                    continue
                start_iso = start.isoformat()
                end_iso = None
                if row.get("enddt"):
                    try:
                        end_iso = _aware(dateparser.parse(row["enddt"])).isoformat()
                    except (ValueError, TypeError, OverflowError):
                        pass
                title = (row.get("title") or "Library event").strip()
                loc = row.get("location") or row.get("campus") or "New Haven Free Public Library"
                eid = str(row.get("id") or title)
                events.append(
                    Event(
                        id=make_id("nhfpl", eid, start_iso),
                        source="nhfpl",
                        source_id=eid,
                        title=title,
                        start=start_iso,
                        end=end_iso,
                        all_day=bool(row.get("all_day")),
                        location=str(loc),
                        description=(row.get("shortdesc") or "").strip(),
                        url=row.get("url") or f"https://nhfpl.libcal.com/event/{eid}",
                        host="New Haven Free Public Library",
                        tags=row.get("categories") or "community",
                        fingerprint=fingerprint(title, start_iso, str(loc)),
                    )
                )
    return events


def fetch_unh(days: int = 14) -> list[Event]:
    """University of New Haven public events (Localist), if the API is up."""
    events: list[Event] = []
    page = 1
    with client() as http:
        while page <= 8:
            response = http.get(UNH_LOCALIST, params={"days": days, "pp": 40, "page": page})
            if response.status_code >= 400:
                break
            payload = response.json()
            rows = payload.get("events") or []
            for wrapper in rows:
                raw = wrapper.get("event") or wrapper
                instances = raw.get("event_instances") or [{}]
                for inst_wrap in instances:
                    inst = inst_wrap.get("event_instance") or inst_wrap
                    start = inst.get("start") or ""
                    if not start:
                        continue
                    source_id = str(inst.get("id") or raw.get("id"))
                    title = (raw.get("title") or "").strip()
                    loc = raw.get("location_name") or raw.get("address") or "University of New Haven"
                    events.append(
                        Event(
                            id=make_id("unh", source_id, start),
                            source="unh",
                            source_id=source_id,
                            title=title,
                            start=start,
                            end=inst.get("end"),
                            all_day=bool(inst.get("all_day")),
                            location=loc,
                            description=(raw.get("description_text") or "")[:1500],
                            url=raw.get("localist_url") or raw.get("url") or "",
                            host="University of New Haven",
                            tags="community, university",
                            fingerprint=fingerprint(title, start, loc),
                        )
                    )
            info = payload.get("page") or {}
            if int(info.get("current") or page) >= int(info.get("total") or page) or not rows:
                break
            page += 1
    return events


def fetch_community() -> list[Event]:
    events: list[Event] = []
    for label, fn in (("NHFPL", fetch_nhfpl), ("UNH", fetch_unh)):
        try:
            events.extend(fn())
        except Exception:
            continue
    return events
