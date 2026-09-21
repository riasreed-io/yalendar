from __future__ import annotations

from html import unescape

from .http import client
from .models import Event, fingerprint, make_id

LOCALIST_URL = "https://events.yale.edu/api/2/events"
LOCALIST_PAGESIZE = 40


def _text(value: str | None) -> str:
    if not value:
        return ""
    return unescape(value).strip()


def _tags(event: dict) -> str:
    names: list[str] = []
    for tag in event.get("tags") or []:
        names.append(tag if isinstance(tag, str) else str(tag))
    filters = event.get("filters") or {}
    for key in ("event_types", "event_topics"):
        for item in filters.get(key) or []:
            name = item.get("name") if isinstance(item, dict) else None
            if name:
                names.append(name)
    return ", ".join(dict.fromkeys(names))


def _host(event: dict) -> str:
    groups = event.get("groups") or []
    names = [g.get("name") for g in groups if isinstance(g, dict) and g.get("name")]
    return ", ".join(names)


def _location(event: dict) -> str:
    parts = [
        _text(event.get("location_name")),
        _text(event.get("room_number")),
        _text(event.get("location")),
        _text(event.get("address")),
    ]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def fetch_localist(days: int = 14, start: str | None = None) -> list[Event]:
    events: list[Event] = []
    page = 1
    with client() as http:
        while True:
            params = {"days": days, "pp": LOCALIST_PAGESIZE, "page": page}
            if start:
                params["start"] = start
            response = None
            for attempt in range(3):
                response = http.get(LOCALIST_URL, params=params)
                if response.status_code != 503:
                    break
            response.raise_for_status()
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
                    title = _text(raw.get("title"))
                    loc = _location(raw)
                    event = Event(
                        id=make_id("localist", source_id, start),
                        source="localist",
                        source_id=source_id,
                        title=title,
                        start=start,
                        end=inst.get("end"),
                        all_day=bool(inst.get("all_day")),
                        location=loc,
                        description=_text(raw.get("description_text") or raw.get("description")),
                        url=_text(raw.get("localist_url") or raw.get("url")),
                        host=_host(raw),
                        tags=_tags(raw),
                        fingerprint=fingerprint(title, start, loc),
                        extra={"experience": raw.get("experience"), "status": raw.get("status")},
                    )
                    events.append(event)
            info = payload.get("page") or {}
            current = int(info.get("current") or page)
            total_pages = int(info.get("total") or current)
            if current >= total_pages or not rows:
                break
            page += 1
            if page > 40:
                break
    return events
