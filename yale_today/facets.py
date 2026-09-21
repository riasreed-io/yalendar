from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .categories import CATEGORY_ORDER, attach_categories

CHANNEL_LABELS = {
    "public": "Public Yale calendars",
    "yale_connect": "Yale Connect",
    "campus_groups": "Campus Groups (SOM)",
    "community": "New Haven community",
}

SOURCE_CHANNEL = {
    "localist": "public",
    "athletics": "public",
    "ics": "public",
    "yale_connect": "yale_connect",
    "campus_groups": "campus_groups",
    "nhfpl": "community",
    "unh": "community",
}

SOURCE_LABELS = {
    "localist": "Yale Events",
    "athletics": "Athletics",
    "ics": "Other calendar",
    "yale_connect": "Yale Connect",
    "campus_groups": "Campus Groups",
    "nhfpl": "NH Free Public Library",
    "unh": "University of New Haven",
}

DEPARTMENTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("som", "School of Management", ("school of management", " som", "som ", "campus_groups")),
    ("college", "Yale College", ("yale college", "undergraduate organization", "yc3", "eli whitney", "first-year")),
    ("law", "Law School", ("law school", " yls", "yale law")),
    ("medicine", "School of Medicine", ("school of medicine", "ysm", "medicine")),
    ("nursing", "School of Nursing", ("nursing", "ysn")),
    ("public_health", "School of Public Health", ("public health", "ysph")),
    ("environment", "School of the Environment", ("school of the environment", " yse", "yse ", "forest forum")),
    ("divinity", "Divinity School", ("divinity", "yds", "marquand")),
    ("drama", "School of Drama", ("drama", "theater", "theatre")),
    ("gsas", "Graduate School", ("gsas", "graduate writing", "postdoctoral", "poorvu")),
    ("seas", "Engineering & Applied Science", ("school of engineering", "seas", "applied science")),
    ("jackson", "Jackson School", ("jackson", "global affairs")),
    ("arts", "Arts & museums", ("yale arts", "art gallery", "schwarzman", "film archive", "music")),
    ("libraries", "Libraries", ("library", "beinecke", "bass library")),
    ("athletics", "Athletics", ("athletics", "bulldogs", "intramural")),
    ("wellbeing", "Health & wellbeing", ("being well", "well-being", "lgbtq", "mental health")),
    ("cultural", "Cultural centers", ("afro-american", "cultural center", "la casa", "native")),
    ("community", "New Haven community", ("nhfpl", "new haven free public", "university of new haven", "community")),
]

ORG_CLEAN = re.compile(
    r"\s*[-–—]?\s*(an undergraduate organization|inc\.?|a student org.*)?\s*$",
    re.I,
)


def channel_for(event: dict) -> str:
    return SOURCE_CHANNEL.get(event.get("source") or "", "public")


def org_name(event: dict) -> str:
    host = (event.get("host") or "").split(",")[0].strip()
    host = ORG_CLEAN.sub("", host).strip(" -")
    if not host:
        if event.get("source") == "athletics":
            return "Yale Athletics"
        if event.get("source") == "localist":
            return "Yale Events"
        return "Unlisted group"
    return host


def department_for(event: dict) -> tuple[str, str]:
    if event.get("source") in {"nhfpl", "unh"}:
        return "community", "New Haven community"
    if event.get("source") == "campus_groups":
        return "som", "School of Management"
    if event.get("source") == "athletics":
        return "athletics", "Athletics"
    blob = " ".join(
        [
            event.get("source") or "",
            event.get("host") or "",
            event.get("tags") or "",
            event.get("title") or "",
        ]
    ).lower()
    for slug, label, needles in DEPARTMENTS:
        if any(n.strip() in blob for n in needles if n.strip()):
            return slug, label
    return "other", "Other units"


def enrich(events: list[dict]) -> list[dict]:
    attach_categories(events)
    for event in events:
        event["channel"] = channel_for(event)
        event["channel_label"] = CHANNEL_LABELS[event["channel"]]
        event["source_label"] = SOURCE_LABELS.get(event.get("source") or "", event.get("source") or "")
        event["org"] = org_name(event)
        slug, label = department_for(event)
        event["dept"] = slug
        event["dept_label"] = label
        event["access"] = "public" if event["channel"] == "public" else "campus"
        event["access_label"] = "Publicly listed" if event["access"] == "public" else "Campus platforms"
    return events


def _as_set(value) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return {part.strip() for part in value.split(",") if part.strip()}
    return {str(part).strip() for part in value if str(part).strip()}


def apply_filters(
    events: list[dict],
    *,
    channel=None,
    dept=None,
    org=None,
    cat=None,
) -> list[dict]:
    enrich(events)
    out = events
    channels = _as_set(channel)
    depts = _as_set(dept)
    orgs = _as_set(org)
    cats = _as_set(cat)
    if channels:
        out = [e for e in out if e["channel"] in channels]
    if depts:
        out = [e for e in out if e["dept"] in depts]
    if orgs:
        out = [e for e in out if e["org"] in orgs]
    if cats:
        out = [e for e in out if e["category"] in cats]
    return out


def _aware(dt: datetime, tz: ZoneInfo) -> datetime:
    if dt.tzinfo:
        return dt.astimezone(tz)
    return dt.replace(tzinfo=tz)


def event_start_local(event: dict, tz: ZoneInfo) -> datetime | None:
    raw = event.get("start") or ""
    try:
        return _aware(datetime.fromisoformat(raw), tz)
    except ValueError:
        return None


def filter_by_time(
    events: list[dict],
    after: str | None,
    *,
    now: datetime,
    tz: ZoneInfo,
) -> list[dict]:
    """Keep events at or after a clock time. 'now' only trims today's date. 'all' keeps everything."""
    mode = (after or "now").strip().lower()
    if mode in {"all", ""}:
        return events
    if mode == "now":
        today = now.date()
        kept = []
        for event in events:
            if event.get("all_day"):
                kept.append(event)
                continue
            start = event_start_local(event, tz)
            if start is None or start.date() != today or start >= now:
                kept.append(event)
        return kept
    try:
        hour, minute = (int(part) for part in mode.split(":", 1))
        clock = time(hour, minute)
    except ValueError:
        return events
    kept = []
    for event in events:
        if event.get("all_day"):
            kept.append(event)
            continue
        start = event_start_local(event, tz)
        if start is None:
            kept.append(event)
            continue
        if start >= datetime.combine(start.date(), clock, tzinfo=tz):
            kept.append(event)
    return kept


def sort_events(events: list[dict], sort: str) -> list[dict]:
    if sort == "org":
        events.sort(key=lambda e: (e.get("org") or "", e.get("start") or "", e.get("title") or ""))
    elif sort == "dept":
        events.sort(key=lambda e: (e.get("dept_label") or "", e.get("start") or "", e.get("title") or ""))
    elif sort == "title":
        events.sort(key=lambda e: ((e.get("title") or "").lower(), e.get("start") or ""))
    else:
        events.sort(key=lambda e: (e.get("start") or "", e.get("title") or ""))
    return events


def group_events(events: list[dict], group_by: str) -> list[dict]:
    if group_by == "none":
        return [{"slug": "all", "label": "All events", "events": events, "count": len(events)}]
    key = {"dept": "dept", "org": "org", "channel": "channel"}.get(group_by, "category")
    label_key = {"dept": "dept_label", "org": "org", "channel": "channel_label"}.get(group_by, "category_label")
    buckets: dict[str, list] = defaultdict(list)
    for event in events:
        buckets[str(event.get(key) or "other")].append(event)
    grouped = []
    if group_by == "category":
        order = list(CATEGORY_ORDER)
        for slug, label in order:
            rows = buckets.get(slug) or []
            if rows:
                grouped.append({"slug": slug, "label": label, "events": rows, "count": len(rows)})
        return grouped
    for slug, rows in sorted(buckets.items(), key=lambda kv: (kv[1][0].get(label_key) or kv[0]).lower()):
        grouped.append(
            {
                "slug": slug,
                "label": rows[0].get(label_key) or slug,
                "events": rows,
                "count": len(rows),
            }
        )
    return grouped


def facet_options(events: list[dict], *, full: bool = False) -> dict:
    depts: dict[str, str] = {}
    dept_counts: dict[str, int] = defaultdict(int)
    orgs: set[str] = set()
    channels: dict[str, int] = defaultdict(int)
    cats: dict[str, int] = defaultdict(int)
    for event in events:
        depts[event["dept"]] = event["dept_label"]
        dept_counts[event["dept"]] += 1
        orgs.add(event["org"])
        channels[event["channel"]] += 1
        cats[event["category"]] += 1
    if full:
        for slug, label, _needles in DEPARTMENTS:
            depts.setdefault(slug, label)
    departments = sorted(
        ({"slug": k, "label": v, "count": dept_counts.get(k, 0)} for k, v in depts.items()),
        key=lambda x: x["label"],
    )
    category_rows = [
        {"slug": slug, "label": label, "count": cats.get(slug, 0)}
        for slug, label in CATEGORY_ORDER
        if full or cats.get(slug, 0)
    ]
    return {
        "departments": departments,
        "orgs": sorted(orgs, key=str.lower),
        "channels": [
            {"slug": slug, "label": CHANNEL_LABELS[slug], "count": channels.get(slug, 0)}
            for slug in CHANNEL_LABELS
        ],
        "categories": category_rows,
    }
