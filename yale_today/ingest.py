from __future__ import annotations

import json
from dataclasses import dataclass, field

from calendar import monthrange
from datetime import date, timedelta

from . import community, connect, db, dedupe, ics_feeds, localist
from .config import CONNECT_FEEDS_PATH


@dataclass
class IngestReport:
    localist: int = 0
    yale_connect: int = 0
    ics: int = 0
    extra_ics: int = 0
    campus_groups: int = 0
    community: int = 0
    total_upserted: int = 0
    connect_login: dict | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "localist": self.localist,
            "yale_connect": self.yale_connect,
            "ics": self.ics,
            "extra_ics": self.extra_ics,
            "campus_groups": self.campus_groups,
            "community": self.community,
            "total_upserted": self.total_upserted,
            "connect_login": (
                {k: v for k, v in self.connect_login.items() if k != "events"}
                if self.connect_login
                else None
            ),
            "errors": self.errors or [],
        }


def _starts(event) -> str:
    return getattr(event, "start", None) or (event.get("start") if isinstance(event, dict) else "") or ""


def in_month(events, month: str) -> list:
    prefix = month.strip()
    if not prefix:
        return events
    return [e for e in events if _starts(e).startswith(prefix)]


def in_window(events, start_day: str, days: int) -> list:
    begin = date.fromisoformat(start_day)
    end = begin + timedelta(days=days)
    kept = []
    for event in events:
        raw = _starts(event)[:10]
        if len(raw) != 10:
            continue
        try:
            when = date.fromisoformat(raw)
        except ValueError:
            continue
        if begin <= when < end:
            kept.append(event)
    return kept


def run_ingest(
    include_connect_login: bool = False,
    headed: bool = False,
    month: str | None = None,
    login_sources: list[str] | None = None,
    days: int | None = None,
    start_day: str | None = None,
) -> IngestReport:
    report = IngestReport(errors=[])
    collected = []
    month = month or ""
    window_days = days
    window_start = start_day
    if window_days and not window_start:
        window_start = today_local().isoformat()
    start = f"{month}-01" if len(month) == 7 else None
    span = 31
    if start:
        year, mon = int(month[:4]), int(month[5:7])
        span = monthrange(year, mon)[1]
    elif window_days:
        start = window_start
        span = window_days

    def keep(events):
        if month:
            return in_month(events, month)
        if window_start and window_days:
            return in_window(events, window_start, window_days)
        return events

    def pull(label: str, fn):
        try:
            return fn()
        except Exception as exc:
            report.errors.append(f"{label}: {exc.__class__.__name__}")
            return []

    if include_connect_login:
        from .connect_login import login_and_capture_ics

        print("Opening Yale Connect, then Campus Groups (SOM). Approve Duo if asked.", flush=True)
        report.connect_login = login_and_capture_ics(
            headed=headed,
            month=month,
            sources=login_sources,
            start_day=window_start or "",
            days=window_days or 0,
        )
        session_events = (report.connect_login or {}).get("events") or []
        if session_events:
            kept = keep(session_events)
            collected.extend(kept)
            by_src = {}
            for ev in session_events:
                src = getattr(ev, "source", None) or (ev.get("source") if isinstance(ev, dict) else "")
                by_src[src] = by_src.get(src, 0) + 1
            report.yale_connect = by_src.get("yale_connect", report.yale_connect)
            report.campus_groups = by_src.get("campus_groups", report.campus_groups)
        urls = ((report.connect_login or {}).get("ics_urls") or [])[:10]
        more = []
        for url in urls:
            try:
                more.extend(ics_feeds.fetch_ics(url, source="yale_connect"))
            except Exception:
                continue
        if more:
            collected.extend(more)
            report.extra_ics += len(more)
        if not report.connect_login or not report.connect_login.get("ok"):
            msg = (report.connect_login or {}).get("message") or "CampusGroups login failed"
            report.errors.append(msg)

    localist_events = pull(
        "Yale Events",
        lambda: localist.fetch_localist(days=span, start=start) if start else localist.fetch_localist(),
    )
    report.localist = len(localist_events)
    collected.extend(keep(localist_events))

    connect_events = pull("Yale Connect public", lambda: connect.fetch_connect_public(limit=1500))
    chunk = keep(connect_events)
    collected.extend(chunk)
    report.yale_connect = max(report.yale_connect, len(chunk))

    som_events = pull("Campus Groups public", lambda: connect.fetch_som_campus_groups(limit=1500))
    chunk = keep(som_events)
    collected.extend(chunk)
    report.campus_groups = max(report.campus_groups, len(chunk))

    community_events = pull("New Haven community", community.fetch_community)
    collected.extend(keep(community_events))
    report.community = len(keep(community_events))

    default_ics = pull("Athletics", ics_feeds.fetch_default_ics)
    default_ics = keep(default_ics)
    report.ics = len(default_ics)
    collected.extend(default_ics)

    extra_urls: list[str] = []
    if CONNECT_FEEDS_PATH.exists():
        try:
            payload = json.loads(CONNECT_FEEDS_PATH.read_text(encoding="utf-8"))
            extra_urls.extend(payload.get("ics_urls") or [])
        except json.JSONDecodeError:
            pass
    for row in db.list_feeds():
        extra_urls.append(row["url"])

    extra_events = []
    for url in dict.fromkeys(extra_urls):
        try:
            extra_events.extend(ics_feeds.fetch_ics(url, source="ics"))
        except Exception:
            continue
    extra_events = keep(extra_events)
    report.extra_ics += len(extra_events)
    collected.extend(extra_events)

    report.total_upserted = db.upsert_events(collected)
    if month and not window_days:
        db.keep_month(month)
    dedupe.apply_dedupe()
    return report
