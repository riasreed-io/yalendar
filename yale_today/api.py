"""JSON API for the React frontend.

Additive: the Jinja views are untouched and still serve every original route.

Shaped around two measurements taken against real data. A month of events was
2.3 MB of JSON, of which ~46% was event descriptions that the UI only shows
when someone expands a single row; and enriching ~2,500 rows cost ~120 ms on
every request, including every keystroke in the search box. So list responses
omit descriptions (fetched per event on demand) and the enriched window is
cached briefly.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date, timedelta

from fastapi import APIRouter, Body, HTTPException, Request, Response

from . import db, ingest
from .assistant import answer as local_answer
from .config import WINDOW_DAYS, now_local, today_local
from .dedupe import events_for_range
from .facets import (
    CHANNEL_LABELS,
    enrich,
    facet_options,
    filter_by_time,
    group_events,
    sort_events,
)
from .agent.tools import data_horizon

router = APIRouter(prefix="/api")

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
MAX_RANGE_DAYS = 92
CACHE_TTL_SECONDS = 60
CACHE_MAX_ENTRIES = 24

SORTS = ["time", "org", "dept", "title"]
GROUPS = ["channel", "category", "dept", "org", "none"]

_cache: dict[tuple, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def _load_window(start: str, end: str, query: str) -> list[dict]:
    """Enriched events for a range, cached briefly.

    Rows are treated as read-only by callers. enrich() is idempotent, so a
    cached row already carries channel/org/dept/category.
    """
    key = (start, end, query)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]

    rows = events_for_range(start, end, q=query or None)
    enrich(rows)

    with _cache_lock:
        if len(_cache) >= CACHE_MAX_ENTRIES:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest, None)
        _cache[key] = (now, rows)
    return rows


def invalidate_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _matches(event: dict, channels, depts, cats, orgs) -> bool:
    if channels and event.get("channel") not in channels:
        return False
    if depts and event.get("dept") not in depts:
        return False
    if cats and event.get("category") not in cats:
        return False
    if orgs and event.get("org") not in orgs:
        return False
    return True


def _event_json(event: dict) -> dict:
    """List shape. Deliberately omits `description`, which was ~46% of the
    payload and is only rendered when a row is expanded."""
    description = event.get("description") or ""
    return {
        "id": event.get("id"),
        "title": event.get("title") or "Untitled event",
        "start": event.get("start") or "",
        "all_day": bool(event.get("all_day")),
        "location": event.get("location") or "",
        "org": event.get("org") or "",
        "url": event.get("url") or "",
        "source": event.get("source") or "",
        "channel": event.get("channel") or "",
        "channel_label": event.get("channel_label") or "",
        "category": event.get("category") or "",
        "category_label": event.get("category_label") or "",
        "dept": event.get("dept") or "",
        "dept_label": event.get("dept_label") or "",
        "also_listed": event.get("also_listed") or [],
        "has_description": bool(description.strip()),
    }


@router.get("/health")
def health() -> dict:
    horizon = data_horizon()
    return {
        "ok": True,
        "today": horizon.today,
        "events": horizon.total_events,
        "data_from": horizon.earliest,
        "data_through": horizon.latest,
    }


@router.get("/events")
def events(request: Request, response: Response,
           start: str | None = None, end: str | None = None,
           after: str = "all", sort: str = "time", group: str = "none") -> dict:
    today = today_local()
    try:
        first = date.fromisoformat(start) if start else today
    except ValueError:
        first = today
    try:
        last = date.fromisoformat(end) if end else first
    except ValueError:
        last = first
    if last < first:
        last = first
    if (last - first).days > MAX_RANGE_DAYS:
        last = first + timedelta(days=MAX_RANGE_DAYS)

    channels = set(request.query_params.getlist("channel"))
    depts = set(request.query_params.getlist("dept"))
    cats = set(request.query_params.getlist("cat"))
    orgs = set(request.query_params.getlist("org"))
    query = (request.query_params.get("q") or "").strip()
    sort = sort if sort in SORTS else "time"
    group = group if group in GROUPS else "none"

    rows = _load_window(first.isoformat(), last.isoformat(), query)
    facets = facet_options(rows, full=True)

    selected = [e for e in rows if _matches(e, channels, depts, cats, orgs)]
    selected = filter_by_time(selected, after, now=now_local(), tz=now_local().tzinfo)
    selected = sort_events(list(selected), sort)

    payload = {
        "start": first.isoformat(),
        "end": last.isoformat(),
        "today": today.isoformat(),
        "total": len(rows),
        "count": len(selected),
        "events": [_event_json(e) for e in selected],
        "facets": facets,
    }
    if group != "none":
        payload["groups"] = [
            {
                "slug": block["slug"],
                "label": block["label"],
                "count": block["count"],
                "ids": [e.get("id") for e in block["events"]],
            }
            for block in group_events(list(selected), group)
        ]
    response.headers["Cache-Control"] = "private, max-age=30"
    return payload


@router.get("/events/{event_id}")
def event_detail(event_id: str) -> dict:
    """Full record including the description, fetched only when a row opens."""
    con = db.connect()
    row = con.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    con.close()
    if row is None:
        raise HTTPException(status_code=404, detail="No such event")
    event = dict(row)
    enrich([event])
    detail = _event_json(event)
    detail["description"] = event.get("description") or ""
    detail["tags"] = event.get("tags") or ""
    detail["end"] = event.get("end") or ""
    return detail


@router.get("/sources")
def sources() -> dict:
    """Provenance for the Sources tab: pulled what, how many, when."""
    rows = db.source_run_summary()
    return {
        "sources": rows,
        "history": db.source_run_history(limit=40),
        "total_in_db": sum(r["in_db"] for r in rows),
    }


@router.get("/meta")
def meta() -> dict:
    return {
        "sorts": SORTS,
        "groups": GROUPS,
        "channels": [{"slug": s, "label": l} for s, l in CHANNEL_LABELS.items()],
        "window_days": WINDOW_DAYS,
    }


# ---------------------------------------------------------------- refresh

_refresh_lock = threading.Lock()
_refresh_state: dict = {"running": False, "finished_at": None, "result": None, "error": None}


def _run_refresh() -> None:
    try:
        report = ingest.run_ingest(include_connect_login=False, days=WINDOW_DAYS)
        result = {
            "upserted": getattr(report, "total_upserted", None)
            or getattr(report, "__dict__", {}).get("total_upserted"),
            "errors": list(getattr(report, "errors", []) or []),
        }
        with _refresh_lock:
            _refresh_state.update(running=False, result=result, error=None,
                                  finished_at=now_local().isoformat())
    except Exception as exc:  # surfaced to the UI, not swallowed
        with _refresh_lock:
            _refresh_state.update(running=False, result=None, error=str(exc),
                                  finished_at=now_local().isoformat())
    finally:
        invalidate_cache()


@router.post("/refresh")
def refresh() -> dict:
    """Start a public ingest in the background.

    A full pull takes tens of seconds, too long to hold a request open, so the
    frontend polls /api/refresh/status. This never runs the Duo scrape.
    """
    with _refresh_lock:
        if _refresh_state["running"]:
            return {"started": False, "running": True}
        _refresh_state.update(running=True, result=None, error=None, finished_at=None)
    threading.Thread(target=_run_refresh, daemon=True).start()
    return {"started": True, "running": True}


@router.get("/refresh/status")
def refresh_status() -> dict:
    with _refresh_lock:
        return dict(_refresh_state)


# ------------------------------------------------------------------ feeds

@router.get("/feeds")
def list_feeds() -> dict:
    return {"urls": [row["url"] for row in db.list_feeds()]}


@router.put("/feeds")
def save_feeds(payload: dict = Body(default={})) -> dict:
    raw = payload.get("urls")
    if isinstance(raw, str):
        urls = [line.strip() for line in raw.splitlines() if line.strip()]
    elif isinstance(raw, list):
        urls = [str(u).strip() for u in raw if str(u).strip()]
    else:
        urls = []
    bad = [u for u in urls if not u.lower().startswith(("http://", "https://"))]
    if bad:
        raise HTTPException(status_code=400, detail=f"Not a URL: {bad[0]}")
    db.replace_feeds(urls)
    return {"urls": urls, "saved": len(urls)}


# -------------------------------------------------------------------- ask

def _ask_local(question: str) -> dict:
    result = local_answer(question)
    return {
        "reply": result.reply,
        "events": [
            {
                "title": e.get("title") or "Untitled event",
                "when": e.get("when_label") or "",
                "location": e.get("location") or "",
                "org": e.get("org") or "",
                "url": e.get("url") or "",
                "channel": e.get("channel") or "public",
            }
            for e in result.events
        ],
        "more": result.more,
        "link": result.link,
        "link_label": result.link_label,
        "suggestions": result.suggestions,
        "engine": "local",
    }


@router.post("/ask")
def ask(payload: dict = Body(default={})) -> dict:
    """Free local search. Same engine as the site's Ask panel; no model, no cost."""
    question = str(payload.get("q") or "").strip()[:300]
    if not question:
        return {"reply": "Ask me what you're looking for — a day, a topic, or both.",
                "events": [], "more": 0, "link": "", "link_label": "",
                "suggestions": [], "engine": "local"}
    return _ask_local(question)


def _agent_allowed(request: Request) -> bool:
    """The agent costs money per question and the site is public, so visitors
    do not get it unless YALENDAR_PUBLIC_AGENT=1 is set deliberately."""
    if os.environ.get("YALENDAR_PUBLIC_AGENT") == "1":
        return True
    host = (request.client.host if request.client else "") or ""
    return host in LOCAL_HOSTS


@router.get("/agent/status")
def agent_status(request: Request) -> dict:
    return {
        "allowed": _agent_allowed(request),
        "configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "public": os.environ.get("YALENDAR_PUBLIC_AGENT") == "1",
    }


@router.post("/agent")
def agent_ask(request: Request, payload: dict = Body(default={})) -> dict:
    question = str(payload.get("q") or "").strip()[:500]
    if not question:
        return {"reply": "Ask me something about campus events.", "tools_used": [],
                "engine": "agent", "error": "empty"}
    if not _agent_allowed(request):
        local = _ask_local(question)
        local["note"] = "The AI assistant is limited to the site owner; this is the free search."
        return local

    from .agent.agent import run_agent

    try:
        result = run_agent(question)
        result["engine"] = "agent"
        return result
    except RuntimeError as exc:
        local = _ask_local(question)
        local["note"] = str(exc)
        return local
