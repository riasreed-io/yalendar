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


def _events_from_rows(rows: list) -> list[Event]:
    """Turn Localist API rows into Events. Shared by the whole-feed and the
    per-group fetchers so both produce identical records."""
    out: list[Event] = []
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
            out.append(
                Event(
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
            )
    return out


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
            events.extend(_events_from_rows(rows))
            # Do NOT trust payload["page"]["total"]: Localist reported 6 pages
            # on one run and 22 minutes later for the same query, silently
            # truncating the ingest to a third of the events. Page until a
            # short page arrives instead, which is self-evidently the end.
            if not rows or len(rows) < LOCALIST_PAGESIZE:
                break
            page += 1
            if page > 60:
                break
    return events


GROUPS_URL = "https://events.yale.edu/api/2/groups"


def fetch_groups() -> list[dict]:
    """Every Yale unit that publishes to the central calendar."""
    out: list[dict] = []
    with client() as http:
        page = 1
        while page <= 20:
            response = http.get(GROUPS_URL, params={"pp": 100, "page": page})
            if response.status_code != 200:
                break
            groups = response.json().get("groups", [])
            if not groups:
                break
            for entry in groups:
                group = entry.get("group", entry)
                if group.get("id"):
                    out.append({"id": group["id"], "name": group.get("name") or ""})
            page += 1
    return out


def fetch_localist_by_group(
    days: int = 31,
    start: str | None = None,
    groups: list[dict] | None = None,
    pause: float = 0.12,
) -> list[Event]:
    """Pull each department's calendar individually.

    The main /api/2/events feed does not surface every group's events - a
    department can publish to Localist and still be absent from it (Council
    on East Asian Studies had three upcoming events missing this way). Asking
    per group is slower but complete, and gives exact attribution.
    """
    import time

    groups = groups if groups is not None else fetch_groups()
    collected: list[Event] = []
    seen_ids: set[str] = set()
    with client() as http:
        for group in groups:
            page = 1
            while page <= 10:
                params = {
                    "group_id": group["id"],
                    "days": days,
                    "pp": LOCALIST_PAGESIZE,
                    "page": page,
                }
                if start:
                    params["start"] = start
                try:
                    response = http.get(LOCALIST_URL, params=params)
                except Exception:
                    break
                if response.status_code != 200:
                    break
                rows = response.json().get("events", [])
                if not rows:
                    break
                batch = _events_from_rows(rows)
                for event in batch:
                    if event.id not in seen_ids:
                        seen_ids.add(event.id)
                        collected.append(event)
                if len(rows) < LOCALIST_PAGESIZE:
                    break
                page += 1
                time.sleep(pause)
            time.sleep(pause)
    return collected
