from __future__ import annotations

import json
from dataclasses import dataclass, field

from calendar import monthrange
from datetime import date, timedelta

from . import community, connect, db, dedupe, ics_feeds, localist
from .config import CONNECT_FEEDS_PATH, today_local


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

    def _log(label: str, events, *, status: str = "ok", detail: str = "",
             authenticated: bool = False, fallback: str = "") -> None:
        """Record what each source produced, so the Sources tab can prove it."""
        from collections import Counter

        counts: Counter = Counter()
        for ev in events or []:
            src = getattr(ev, "source", None)
            if src is None and isinstance(ev, dict):
                src = ev.get("source")
            counts[src or fallback] += 1
        if not counts and fallback:
            counts[fallback] = 0
        for src, n in counts.items():
            if not src:
                continue
            db.record_source_run(src, n, label=label, status=status,
                                 detail=detail, authenticated=authenticated)

    def pull(label: str, fn, source: str = ""):
        try:
            return fn()
        except Exception as exc:
            report.errors.append(f"{label}: {exc.__class__.__name__}")
            # A failed source must still leave a record, otherwise an outage
            # looks identical to a source that was never configured.
            if source:
                db.record_source_run(
                    source, 0, label=label, status="error",
                    detail=f"{exc.__class__.__name__}: {exc}"[:200])
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

    # Every Localist instance, not just the central calendar: Yale schools can
    # run their own (Jackson does), and those events appear nowhere centrally.
    report.localist = 0
    for inst_source, inst_base, inst_host in localist.LOCALIST_INSTANCES:
        label = ("Yale Events (Localist)" if inst_source == "localist"
                 else f"{inst_host or inst_source} (Localist)")
        rows = pull(
            label,
            lambda b=inst_base, s_=inst_source, h=inst_host: localist.fetch_localist(
                days=span, start=start, base_url=b, source=s_, default_host=h)
            if start else localist.fetch_localist(base_url=b, source=s_, default_host=h),
            source=inst_source,
        )
        report.localist += len(rows)
        kept_rows = keep(rows)
        collected.extend(kept_rows)
        _log(label, kept_rows, fallback=inst_source)

    connect_events = pull("Yale Connect (public)",
                          lambda: connect.fetch_connect_public(limit=1500),
                          source="yale_connect")
    chunk = keep(connect_events)
    collected.extend(chunk)
    report.yale_connect = max(report.yale_connect, len(chunk))
    _log("Yale Connect (public)", chunk, fallback="yale_connect")

    som_events = pull("SOM Campus Groups (public)",
                      lambda: connect.fetch_som_campus_groups(limit=1500),
                      source="campus_groups")
    chunk = keep(som_events)
    collected.extend(chunk)
    report.campus_groups = max(report.campus_groups, len(chunk))
    _log("SOM Campus Groups (public)", chunk, fallback="campus_groups")

    community_events = pull("New Haven community", community.fetch_community,
                            source="community")
    kept_community = keep(community_events)
    collected.extend(kept_community)
    report.community = len(kept_community)
    _log("New Haven community", kept_community)

    default_ics = pull("Yale Athletics (ICS)", ics_feeds.fetch_default_ics,
                       source="athletics")
    default_ics = keep(default_ics)
    report.ics = len(default_ics)
    collected.extend(default_ics)
    _log("Yale Athletics (ICS)", default_ics, fallback="athletics")

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
    if extra_urls:
        _log(f"Extra ICS feeds ({len(set(extra_urls))})", extra_events, fallback="ics")

    report.total_upserted = db.upsert_events(collected)
    if month and not window_days:
        db.keep_month(month)
    dedupe.apply_dedupe()
    return report
