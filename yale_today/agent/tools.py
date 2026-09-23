"""Agent tools.

Each one is a plain typed function over the existing Yalendar data layer, so
they can be called and tested directly without a model. agent.py just hands
this list to the Agent.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..assistant import MAX_RESULTS, _when_label, answer as natural_answer, parse, search
from ..categories import CATEGORY_ORDER
from ..config import now_local, today_local
from ..db import connect
from ..dedupe import events_for_range
from ..facets import CHANNEL_LABELS, DEPARTMENTS, enrich
from .models import DataHorizon, EventSearchResult, EventSummary

TOOL_RESULT_LIMIT = 12


def _to_summary(event: dict, today: date) -> EventSummary:
    return EventSummary(
        title=event.get("title") or "Untitled event",
        start=event.get("start") or "",
        when=event.get("when_label") or _when_label(event, today=today),
        all_day=bool(event.get("all_day")),
        location=event.get("location") or "",
        organization=event.get("org") or "",
        url=event.get("url") or "",
        source=event.get("source") or "",
        channel=event.get("channel") or "",
        channel_label=event.get("channel_label") or "",
        category=event.get("category") or "",
        department=event.get("dept_label") or "",
    )


def search_events(
    start_date: str,
    end_date: str,
    keyword: str = "",
    category: str = "",
    department: str = "",
    source: str = "",
    limit: int = TOOL_RESULT_LIMIT,
) -> EventSearchResult:
    """Find campus events in a date range.

    Args:
        start_date: First day to include, as YYYY-MM-DD.
        end_date: Last day to include, inclusive, as YYYY-MM-DD.
        keyword: Optional free text matched against title, description, host and venue.
        category: Optional category slug, e.g. talks, arts, sports, social, workshops.
        department: Optional school slug, e.g. som, law, medicine, jackson, college.
        source: Optional channel slug: public, yale_connect, campus_groups, community.
        limit: Maximum events to return.
    """
    today = today_local()
    try:
        date.fromisoformat(start_date)
        date.fromisoformat(end_date)
    except ValueError:
        return EventSearchResult(note="Dates must be YYYY-MM-DD.")

    rows = events_for_range(start_date, end_date)
    enrich(rows)

    needle = keyword.strip().lower()
    matched = []
    for event in rows:
        if category and event.get("category") != category:
            continue
        if department and event.get("dept") != department:
            continue
        if source and event.get("channel") != source:
            continue
        if needle:
            hay = " ".join(
                [
                    event.get("title") or "",
                    event.get("description") or "",
                    event.get("host") or "",
                    event.get("location") or "",
                    event.get("tags") or "",
                ]
            ).lower()
            if needle not in hay:
                continue
        matched.append(event)

    matched.sort(key=lambda e: (bool(e.get("all_day")), e.get("start") or ""))
    capped = max(1, min(int(limit or TOOL_RESULT_LIMIT), 40))
    return EventSearchResult(
        events=[_to_summary(e, today) for e in matched[:capped]],
        total=len(matched),
        returned=min(len(matched), capped),
        truncated=len(matched) > capped,
        window_start=start_date,
        window_end=end_date,
    )


def search_events_in_words(question: str) -> EventSearchResult:
    """Search using a plain-English phrase such as "free food this week".

    Resolves relative dates, dayparts, topics and schools the same way the
    site's own search box does. Prefer this when the user's phrasing is
    vague; use search_events when you already know exact dates.
    """
    result = natural_answer(question)
    today = today_local()
    return EventSearchResult(
        events=[_to_summary(e, today) for e in result.events],
        total=len(result.events) + result.more,
        returned=len(result.events),
        truncated=result.more > 0,
        window_start=result.query.start.isoformat(),
        window_end=result.query.end.isoformat(),
        note=result.reply,
    )


def data_horizon() -> DataHorizon:
    """Report today's date and how far the loaded calendar data actually runs.

    Call this before telling someone nothing is scheduled, so you can tell
    the difference between "no events" and "no data loaded yet".
    """
    con = connect()
    row = con.execute(
        "SELECT min(substr(start,1,10)), max(substr(start,1,10)), count(*) FROM events"
    ).fetchone()
    con.close()
    return DataHorizon(
        earliest=row[0] if row else None,
        latest=row[1] if row else None,
        total_events=int(row[2]) if row and row[2] else 0,
        today=today_local().isoformat(),
    )


def list_filters() -> dict[str, list[str]]:
    """List the category, school and source slugs that search_events accepts."""
    return {
        "categories": [slug for slug, _label in CATEGORY_ORDER],
        "departments": [slug for slug, _label, _needles in DEPARTMENTS],
        "sources": list(CHANNEL_LABELS),
    }


ALL_TOOLS = [search_events, search_events_in_words, data_horizon, list_filters]
