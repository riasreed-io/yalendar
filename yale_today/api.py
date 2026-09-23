"""JSON API consumed by the React frontend.

The Jinja views stay exactly as they are; this is an additive layer so the
Vite app can read the same data over CORS.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

from fastapi import APIRouter, Body, Request

from .assistant import answer as local_answer
from .config import now_local, today_local
from .dedupe import events_for_range
from .facets import apply_filters, facet_options, filter_by_time
from .agent.tools import data_horizon

router = APIRouter(prefix="/api")

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def _event_json(event: dict) -> dict:
    return {
        "id": event.get("id"),
        "title": event.get("title") or "Untitled event",
        "start": event.get("start") or "",
        "all_day": bool(event.get("all_day")),
        "location": event.get("location") or "",
        "org": event.get("org") or "",
        "url": event.get("url") or "",
        "description": event.get("description") or "",
        "source": event.get("source") or "",
        "channel": event.get("channel") or "",
        "channel_label": event.get("channel_label") or "",
        "category": event.get("category") or "",
        "category_label": event.get("category_label") or "",
        "dept": event.get("dept") or "",
        "dept_label": event.get("dept_label") or "",
        "also_listed": event.get("also_listed") or [],
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
def events(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    after: str = "all",
) -> dict:
    """Events in a date range, with facet counts for the filter chips."""
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
    # Guard against an unbounded scan from a hand-edited URL.
    if (last - first).days > 92:
        last = first + timedelta(days=92)

    channels = request.query_params.getlist("channel")
    depts = request.query_params.getlist("dept")
    cats = request.query_params.getlist("cat")
    orgs = request.query_params.getlist("org")
    query = (request.query_params.get("q") or "").strip()

    raw = events_for_range(first.isoformat(), last.isoformat(), q=query or None)
    facets = facet_options(apply_filters(list(raw)), full=True)
    selected = apply_filters(list(raw), channel=channels, dept=depts, org=orgs, cat=cats)
    selected = filter_by_time(selected, after, now=now_local(), tz=now_local().tzinfo)

    return {
        "start": first.isoformat(),
        "end": last.isoformat(),
        "today": today.isoformat(),
        "total": len(raw),
        "count": len(selected),
        "events": [_event_json(e) for e in selected],
        "facets": facets,
    }


@router.post("/ask")
def ask(payload: dict = Body(default={})) -> dict:
    """Free local search. Same engine as the site's Ask panel; no model, no cost."""
    question = str(payload.get("q") or "").strip()[:300]
    if not question:
        return {
            "reply": "Ask me what you're looking for — a day, a topic, or both.",
            "events": [], "more": 0, "link": "", "link_label": "",
            "suggestions": [], "engine": "local",
        }
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


def _agent_allowed(request: Request) -> bool:
    """The agent costs money per question and the site is public.

    Off by default for visitors: only local requests may run it, unless
    YALENDAR_PUBLIC_AGENT=1 is set deliberately.
    """
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
    """Model-backed answer. Gated; falls back to the local engine when refused."""
    question = str(payload.get("q") or "").strip()[:500]
    if not question:
        return {"reply": "Ask me something about campus events.", "tools_used": [],
                "engine": "agent", "error": "empty"}
    if not _agent_allowed(request):
        local = ask({"q": question})
        local["engine"] = "local"
        local["note"] = "The AI assistant is limited to the site owner; this is the free search."
        return local

    from .agent.agent import run_agent

    try:
        result = run_agent(question)
        result["engine"] = "agent"
        return result
    except RuntimeError as exc:
        local = ask({"q": question})
        local["engine"] = "local"
        local["note"] = str(exc)
        return local
