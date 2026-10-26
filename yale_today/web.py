from __future__ import annotations

import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import api, assistant, db, ingest
from .auth import dashboard_password
from .config import (
    MODE,
    ROOT,
    SHARED_INVITE,
    TZINFO,
    WINDOW_DAYS,
    demo_meta,
    is_demo,
    now_local,
    personal_files_present,
    signin_allowed,
    today_local,
    writes_allowed,
)
from .dedupe import events_for_day, events_for_range
from .facets import apply_filters, facet_options, filter_by_time, group_events, sort_events

app = FastAPI(title="Yalendar")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET") or dashboard_password() + "-session",
    same_site="lax",
    https_only=os.environ.get("YALE_TODAY_HTTPS") == "1",
)
templates = Jinja2Templates(directory=str(ROOT / "yale_today" / "templates"))

# The React frontend runs on its own origin in development, and Vite picks a
# different port whenever the default is taken, so match any loopback port
# rather than a fixed list. Deployed origins go in YALENDAR_CORS_ORIGINS.
_cors_origin_regex = r"http://(localhost|127\.0\.0\.1)(:\d+)?"
_cors_origins = [
    origin.strip()
    for origin in os.environ.get("YALENDAR_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
# Event JSON is highly repetitive and compresses roughly 8x.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(api.router)


def format_when(start: str, all_day: int) -> str:
    if all_day:
        return "All day"
    try:
        dt = datetime.fromisoformat(start)
        if dt.tzinfo:
            dt = dt.astimezone(TZINFO)
        return dt.strftime("%-I:%M %p")
    except ValueError:
        return start[11:16] if len(start) >= 16 else start


def format_daylabel(iso: str) -> str:
    """2026-10-25 -> 'Sat, Oct 25'. The toolbar shows a date people read."""
    try:
        return date.fromisoformat((iso or "")[:10]).strftime("%a, %b %-d")
    except ValueError:
        return iso or ""


templates.env.filters["when"] = format_when
templates.env.filters["daylabel"] = format_daylabel
app.mount("/static", StaticFiles(directory=str(ROOT / "yale_today" / "static")), name="static")

def _boot() -> None:
    """Whatever this build is, make it be only that thing.

    Demo builds rebuild their database from the committed snapshot on every
    start, so a stale or hand-edited file left on a volume can never be
    served as the demo. Any build that is not personal shouts if it can see
    a Yale session -- a wrong .dockerignore line should not be the only
    thing standing between a sign-in and a public server.
    """
    if is_demo():
        from . import demo

        count = demo.ensure()
        print(f"[yalendar] demo mode: {count:,} events from "
              f"{demo_meta().get('as_of', '?')[:10]} snapshot", flush=True)
    if MODE != "personal":
        stray = personal_files_present()
        if stray:
            print("[yalendar] WARNING: a Yale sign-in is visible to this "
                  f"{MODE} build: {', '.join(p.name for p in stray)}. "
                  "Nothing will read it, but it should not be here.",
                  flush=True)
    db.ensure_shared_invite()


_boot()


# Mode is in every template: the banner, the disabled buttons and the
# Connect page all have to agree about what this build can do.
templates.env.globals.update(
    mode=MODE,
    is_demo=is_demo(),
    can_write=writes_allowed(),
    can_sign_in=signin_allowed(),
    demo_meta=demo_meta(),
)
SORTS = [
    ("time", "Time"),
    ("org", "Organization"),
    ("dept", "Department"),
    ("title", "Title"),
]
TIME_STEP_COUNT = 24
WEEK_COLUMN_LIMIT = 8
TIME_MARKS = (
    ("00:00", "12 am"),
    ("04:00", "4 am"),
    ("08:00", "8 am"),
    ("12:00", "12 pm"),
    ("16:00", "4 pm"),
    ("20:00", "8 pm"),
)
GROUPS = [
    ("channel", "Source"),
    ("category", "Category"),
    ("dept", "Department"),
    ("org", "Organization"),
    ("none", "One list"),
]


def _logged_in(request: Request) -> bool:
    return True


_refresh_lock = threading.Lock()
_last_window_refresh = 0.0


def _refresh_month_window() -> None:
    global _last_window_refresh
    if not writes_allowed():
        return
    with _refresh_lock:
        now = time.time()
        if now - _last_window_refresh < 20 * 60:
            return
        _last_window_refresh = now
    try:
        ingest.run_ingest(include_connect_login=False, days=WINDOW_DAYS)
    except Exception:
        with _refresh_lock:
            _last_window_refresh = 0.0


def _start_window_refresh() -> None:
    threading.Thread(target=_refresh_month_window, daemon=True).start()


def _parse_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_parse_list(item))
        seen: set[str] = set()
        unique: list[str] = []
        for item in out:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _clock_from_step(step: int) -> str:
    step = max(0, min(TIME_STEP_COUNT - 1, int(step)))
    return f"{step:02d}:00"


def _step_from_clock(clock: str) -> int:
    try:
        hour, _minute = (int(part) for part in clock.split(":", 1))
    except ValueError:
        return 0
    return max(0, min(TIME_STEP_COUNT - 1, hour))


def _after_param(request: Request, *, default: str) -> str:
    raw = (request.query_params.get("after") or "").strip()
    if raw in {"all", "now"}:
        return raw
    if raw.isdigit():
        return _clock_from_step(int(raw))
    if not raw:
        return default
    if len(raw) >= 4 and raw[0].isdigit() and ":" in raw:
        return _clock_from_step(_step_from_clock(raw[:5]))
    return default


def _after_step(after: str, now: datetime) -> int:
    if after in {"all", "now"}:
        return _step_from_clock(now.strftime("%H:%M"))
    if after and ":" in after:
        return _step_from_clock(after)
    return 0


def _after_label(after: str) -> str:
    if after == "all":
        return "All times"
    if after == "now":
        return "Now"
    try:
        hour, minute = (int(part) for part in after.split(":", 1))
        suffix = "AM" if hour < 12 else "PM"
        hour12 = hour % 12 or 12
        return f"{hour12}:{minute:02d} {suffix}"
    except ValueError:
        return after


def _time_ctx(after: str, now: datetime) -> dict:
    last = TIME_STEP_COUNT - 1
    marks = []
    for value, label in TIME_MARKS:
        step = _step_from_clock(value)
        marks.append({"value": value, "label": label, "pct": round(100 * step / last, 2)})
    return {
        "time_marks": marks,
        "after_step": _after_step(after, now),
        "after_label": _after_label(after),
        "time_max": last,
        "all_times": after == "all",
    }


def _query_list(request: Request, name: str) -> list[str]:
    return _parse_list(request.query_params.getlist(name))


def _qs(**parts) -> str:
    pairs: list[tuple[str, str]] = []
    for key, value in parts.items():
        if value in (None, "", [], ()):
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                if item not in (None, ""):
                    pairs.append((key, str(item)))
        else:
            pairs.append((key, str(value)))
    return ("?" + urlencode(pairs)) if pairs else "?"


def _filter_href(path: str, state: dict):
    def href(**overrides) -> str:
        merged = {**state, **overrides}
        return path + _qs(**merged)

    def toggle(key: str, slug: str) -> str:
        current = list(state.get(key) or [])
        if slug in current:
            current = [item for item in current if item != slug]
        else:
            current = current + [slug]
        return href(**{key: current})

    return href, toggle


@app.get("/healthz")
def healthz():
    """Liveness probe for the host's health check.

    Deliberately trivial: no template, no filtering, one indexed count.
    A probe that renders the day view would make a slow page look like a
    dead service and roll back a working deploy.
    """
    con = db.connect()
    count = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    con.close()
    return {"ok": True, "mode": MODE, "events": count,
            "today": today_local().isoformat()}


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None, invite: str | None = None):
    if _logged_in(request):
        return RedirectResponse("/calendar", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error, "invite": invite or request.query_params.get("invite") or ""},
    )


@app.post("/login")
def login_submit(request: Request, invite: str = Form("")):
    if db.invite_ok(invite):
        request.session["ok"] = True
        request.session["invite"] = SHARED_INVITE
        return RedirectResponse("/calendar", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "That invite code is not valid.", "invite": invite.strip()},
        status_code=401,
    )


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/", response_class=HTMLResponse)
def day_view(
    request: Request,
    day: str | None = None,
    cal: str | None = None,
    source: str | None = None,
    channel: str | None = None,
    dept: str | None = None,
    org: str | None = None,
    q: str | None = None,
    cat: str | None = None,
    sort: str | None = None,
    group: str | None = None,
):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=302)
    today = today_local().isoformat()
    day = day or today
    try:
        date.fromisoformat(day)
    except ValueError:
        # A malformed ?day= (typo, stale link, crawler) used to raise straight
        # out of the view as a 500. Fall back to today instead.
        day = today
    sort = sort if sort in {s[0] for s in SORTS} else "time"
    group = group if group in {g[0] for g in GROUPS} else "channel"
    now = now_local()
    # "From 9pm" is a statement about what is left of TODAY. Carrying that
    # default onto another day hid every morning and afternoon event, which
    # looked like the day having no events at all. Only a time the user chose
    # explicitly travels with them.
    chose_time = bool((request.query_params.get("after") or "").strip())
    after = _after_param(
        request,
        default=_clock_from_step(_step_from_clock(now.strftime("%H:%M"))) if day == today else "all",
    )
    channels = _query_list(request, "channel")
    depts = _query_list(request, "dept")
    cats = _query_list(request, "cat")
    units = _query_list(request, "unit")
    orgs = _query_list(request, "org") or ([org] if org else [])
    raw = events_for_day(day, source=source or None, q=q or None)
    facets = facet_options(apply_filters(list(raw)))
    events = apply_filters(
        list(raw),
        channel=channels,
        dept=depts,
        org=orgs,
        cat=cats,
        unit=units,
    )
    events = filter_by_time(events, after, now=now, tz=TZINFO)
    events = sort_events(events, sort)
    grouped = group_events(events, group)
    prev_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    next_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    selected = date.fromisoformat(day)
    shown = _parse_month(cal, selected)
    state = {
        "day": day,
        "cal": shown.isoformat()[:7],
        "source": source or "",
        "channel": channels,
        "dept": depts,
        "org": orgs[0] if len(orgs) == 1 else "",
        "q": q or "",
        "cat": cats,
        "unit": units,
        "after": after if chose_time else "",
        "sort": sort,
        "group": group,
    }
    href, toggle = _filter_href("/", state)

    mini = build_mini_month(
        shown,
        date.fromisoformat(today),
        selected=selected,
        click=lambda d: href(day=d.isoformat(), cal=d.isoformat()[:7]),
        month_nav=lambda m: href(cal=m),
    )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            **state,
            "today": today,
            "prev_day": prev_day,
            "next_day": next_day,
            "groups": grouped,
            "facets": facets,
            "sorts": SORTS,
            "groupings": GROUPS,
            "count": len(events),
            "total": len(raw),
            "notice": request.query_params.get("notice"),
            "href": href,
            "toggle": toggle,
            "mini": mini,
            **_time_ctx(after, now),
        },
    )


ASK_EXAMPLES = [
    "free food this week",
    "what's happening tonight",
    "talks tomorrow",
    "concerts this weekend",
    "SOM events Friday",
    "career events next week",
]


# Available to every template, so the docked panel needs no route changes.
templates.env.globals["ask_examples"] = ASK_EXAMPLES


def _agent_reply(question: str, request: Request | None) -> dict:
    """The model's answer, or {} if it is not available right now.

    The chat panel used to call the local keyword search and nothing else,
    so the agent was unreachable from the only interface most people ever
    see. It now answers here when it can, and the panel says which engine
    replied -- an assistant that quietly degrades to keyword matching
    without saying so is worse than one that admits it.

    Everything that can stop it -- no credential, not the site owner,
    budget spent, model error -- falls through to the free search rather
    than to an error.
    """
    from .api import _agent_allowed
    from .agent import budget
    from .agent.agent import credential, run_agent

    if request is None or not _agent_allowed(request):
        return {}
    if not credential()[0]:
        return {}

    caller = (request.client.host if request.client else "") or ""
    allowance = budget.check(caller)
    if not allowance.ok:
        return {"note": f"AI answers are paused: {allowance.reason}."}

    try:
        result = run_agent(question)
    except Exception as exc:
        return {"note": f"{exc.__class__.__name__}: {exc}"[:200]}
    budget.record(caller, result.get("usage") or {})
    result["reply"] = _plain(result.get("reply") or "")
    return result


_MD = re.compile(r"(\*\*|__|`)")


def _plain(text: str) -> str:
    """Strip the Markdown the model sometimes emits anyway.

    The prompt asks for plain text because the bubble renders literally,
    but an instruction is not a guarantee, and `**free food**` on screen
    reads as a bug. Only the inline emphasis markers are removed -- the
    words, line breaks and punctuation are left exactly as written.
    """
    return _MD.sub("", text)


def _ask_payload(question: str, request: Request | None = None) -> dict:
    """Shared by the page and the fetch endpoint so both answer identically."""
    result = assistant.answer(question)
    agent = _agent_reply(question, request)
    return {
        "question": question,
        "reply": agent.get("reply") or result.reply,
        "engine": "agent" if agent.get("reply") else "local",
        "tools_used": agent.get("tools_used") or [],
        "note": agent.get("note", ""),
        "local_reply": result.reply,
        "events": [
            {
                "title": event.get("title") or "Untitled event",
                "when": event.get("when_label") or "",
                "location": event.get("location") or "",
                "org": event.get("org") or "",
                "url": event.get("url") or "",
                "channel": event.get("channel") or "public",
                "channel_label": event.get("channel_label") or "",
            }
            for event in result.events
        ],
        "more": result.more,
        "link": result.link,
        "link_label": result.link_label,
        "suggestions": result.suggestions,
    }


@app.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request, q: str | None = None):
    """Chat assistant. Server-renders the first answer so it works without JS."""
    question = (q or "").strip()
    answer = _ask_payload(question, request) if question else None
    return templates.TemplateResponse(
        request,
        "ask.html",
        {
            "question": question,
            "answer": answer,
        },
    )


@app.post("/ask")
def ask_api(request: Request, q: str = Form("")):
    question = (q or "").strip()[:300]
    if not question:
        return {"reply": "Ask me what you're looking for — a day, a topic, or both.",
                "events": [], "more": 0, "link": "", "link_label": "",
                "suggestions": ASK_EXAMPLES[:3], "engine": "local"}
    return _ask_payload(question, request)


@app.get("/friends", response_class=HTMLResponse)
def friends(request: Request):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request,
        "friends.html",
        {
            "shared": SHARED_INVITE,
            "login_url": f"{request.base_url}login",
        },
    )


# Every source Yalendar is meant to pull, so the Sources tab can show a
# source that has gone quiet rather than silently omitting it.
EXPECTED_SOURCES = [
    ("localist", "Yale Events (Localist)", "events.yale.edu", "public"),
    ("localist_jackson", "Jackson School (own Localist)",
     "events.jackson.yale.edu", "public"),
    ("localist_som", "SOM calendar (own Localist)",
     "calendar.som.yale.edu", "public"),
    ("yale_connect", "Yale Connect", "yaleconnect.yale.edu", "public + signed in"),
    ("campus_groups", "SOM Campus Groups", "groups.som.yale.edu", "public + signed in"),
    ("athletics", "Yale Athletics", "yalebulldogs.com", "public ICS"),
    ("res_college", "Residential colleges", "Google Calendar", "public ICS"),
    ("nhfpl", "New Haven Free Public Library", "nhfpl.libcal.com", "public"),
    ("unh", "University of New Haven", "newhaven.edu", "public"),
    ("ics", "Extra ICS feeds", "set under Feeds", "public ICS"),
]


@app.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request):
    """Provenance: what was pulled, how many, and when."""
    rows = {row["source"]: row for row in db.source_run_summary()}
    table = []
    for slug, label, origin, kind in EXPECTED_SOURCES:
        row = rows.get(slug, {})
        table.append(
            {
                "slug": slug,
                "label": label,
                "origin": origin,
                "kind": kind,
                "in_db": row.get("in_db", 0),
                "last_count": row.get("last_count"),
                "ran_at": row.get("ran_at"),
                "status": row.get("status") or "never run",
                "detail": row.get("detail") or "",
                "authenticated": row.get("authenticated", False),
                "first_date": row.get("first_date"),
                "last_date": row.get("last_date"),
            }
        )
    # Anything recorded that is not in the expected list still gets shown.
    for slug, row in rows.items():
        if slug not in {s for s, *_ in EXPECTED_SOURCES}:
            table.append({**row, "slug": slug, "origin": "-", "kind": "-",
                          "label": row.get("label") or slug})
    total = sum(r["in_db"] for r in table)
    healthy = sum(1 for r in table if r["status"] == "ok" and r["in_db"])
    return templates.TemplateResponse(
        request,
        "sources.html",
        {
            "rows": table,
            "history": db.source_run_history(limit=40),
            "total": total,
            "healthy": healthy,
            "expected": len(EXPECTED_SOURCES),
            "today": today_local().isoformat(),
        },
    )


# One background sign-in at a time, with its log kept in memory so the
# page can show what the browser window is doing.
_connect_state: dict = {"running": False, "lines": [], "finished": ""}


def _connect_status() -> dict:
    """What the saved Yale session currently looks like, from disk."""
    import json as _json

    from .config import CONNECT_STATUS_PATH, SESSION_STATE_PATH

    saved = SESSION_STATE_PATH.is_file()
    payload: dict = {}
    if CONNECT_STATUS_PATH.is_file():
        try:
            payload = _json.loads(CONNECT_STATUS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
    platforms = payload.get("platforms") or {}
    return {
        "saved_session": saved,
        "checked": bool(platforms),
        "platforms": [
            {"source": k, **v} for k, v in sorted(platforms.items())
        ],
        "running": _connect_state["running"],
        "lines": _connect_state["lines"][-20:],
        "finished": _connect_state["finished"],
    }


@app.get("/settings")
def settings_redirect():
    return RedirectResponse("/connect", status_code=308)


@app.get("/connect", response_class=HTMLResponse)
def connect_page(request: Request):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=302)
    urls = "\n".join(row["url"] for row in db.list_feeds()) if writes_allowed() else ""
    host = (request.client.host if request.client else "") or ""
    return templates.TemplateResponse(
        request,
        "connect.html",
        {
            "urls": urls,
            "status": _connect_status(),
            # Opening a browser window only makes sense for the person
            # sitting at the machine, so the button needs both a personal
            # build and a loopback request.
            "local_request": host in {"127.0.0.1", "::1", "localhost", "testclient"},
            "sources": EXPECTED_SOURCES,
        },
    )


@app.post("/connect/start")
def connect_start(request: Request):
    """Open Yale's own sign-in page in a real browser on this machine.

    Yalendar never sees a NetID or a password: the window goes to Yale's
    CAS page, you type into Yale's form, Duo goes to your phone, and the
    only thing that comes back here is a session cookie written to your own
    data directory. There is no credential field anywhere in this app, and
    this route cannot run on a shared build.
    """
    host = (request.client.host if request.client else "") or ""
    if not signin_allowed() or host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return RedirectResponse("/connect?notice=signin-unavailable", status_code=302)
    if _connect_state["running"]:
        return RedirectResponse("/connect?notice=signin-running", status_code=302)

    def _run() -> None:
        _connect_state.update(running=True, lines=["Opening a browser window..."],
                              finished="")
        try:
            from . import session_login

            report = session_login.interactive_login(wait_seconds=600)
            for check in report.checks:
                _connect_state["lines"].append(
                    f"{check.name}: {'signed in' if check.signed_in else 'not signed in'}"
                    f" ({check.rows} events)")
            _connect_state["finished"] = "ok" if report.ok else "partial"
        except Exception as exc:
            _connect_state["lines"].append(f"{exc.__class__.__name__}: {exc}")
            _connect_state["finished"] = "error"
        finally:
            _connect_state["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return RedirectResponse("/connect?notice=signin-started", status_code=302)


@app.get("/connect/status")
def connect_status_api():
    return _connect_status()


@app.post("/settings")
def settings_save(request: Request, urls: str = Form("")):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=302)
    if not writes_allowed():
        return RedirectResponse("/connect?notice=demo-frozen", status_code=302)
    db.replace_feeds([line.strip() for line in urls.splitlines() if line.strip()])
    return RedirectResponse("/connect?saved=1", status_code=302)


@app.post("/refresh")
def refresh(request: Request):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=302)
    if not writes_allowed():
        return RedirectResponse(
            f"/{request.query_params.get('next') or 'calendar'}?notice=demo-frozen",
            status_code=302)
    month = request.query_params.get("month")
    if not month:
        day = request.query_params.get("day") or today_local().isoformat()
        month = day[:7]
    try:
        report = ingest.run_ingest(include_connect_login=False, days=WINDOW_DAYS)
        notice = "refresh-partial" if report.errors else "refreshed"
    except Exception:
        notice = "refresh-failed"
    dest = request.query_params.get("next") or "calendar"
    if dest == "day":
        day = request.query_params.get("day") or today_local().isoformat()
        return RedirectResponse(f"/?day={day}&notice={notice}", status_code=302)
    if dest == "sources":
        return RedirectResponse(f"/sources?notice={notice}", status_code=302)
    if dest == "week":
        start = request.query_params.get("start") or today_local().isoformat()
        return RedirectResponse(f"/week?start={start}&notice={notice}", status_code=302)
    return RedirectResponse(f"/calendar?month={month}&notice={notice}", status_code=302)


def _month_weeks(year: int, month: int) -> list[list[date]]:
    first = date(year, month, 1)
    start = first - timedelta(days=(first.weekday() + 1) % 7)
    weeks = []
    cursor = start
    for _ in range(6):
        week = []
        for _day in range(7):
            week.append(cursor)
            cursor += timedelta(days=1)
        weeks.append(week)
        if cursor.month != month and cursor.day > 7:
            break
    return weeks


def _parse_month(value: str | None, fallback: date) -> date:
    if value and len(value) == 7:
        try:
            return date(int(value[:4]), int(value[5:7]), 1)
        except ValueError:
            pass
    return date(fallback.year, fallback.month, 1)


def _timed_first(items: list[dict]) -> list[dict]:
    """Timed events before all-day ones, each in start order.

    Multi-day exhibitions are stored as all-day events on every date they run,
    so a plain chronological sort put the same six gallery shows at the top of
    all seven week columns and pushed the day's actual talks out of the
    visible slice. They are still listed, just after the things with a time.
    """
    return sorted(
        items,
        key=lambda e: (1 if e.get("all_day") else 0, e.get("start") or ""),
    )


def build_mini_month(
    shown: date,
    today: date,
    *,
    selected: date | None = None,
    week_start: date | None = None,
    click,
    month_nav,
) -> dict:
    week_days: set[str] = set()
    if week_start:
        week_days = {(week_start + timedelta(days=i)).isoformat() for i in range(7)}
    prev_shown = (
        date(shown.year - 1, 12, 1) if shown.month == 1 else date(shown.year, shown.month - 1, 1)
    )
    next_shown = (
        date(shown.year + 1, 1, 1) if shown.month == 12 else date(shown.year, shown.month + 1, 1)
    )
    weeks = []
    for week in _month_weeks(shown.year, shown.month):
        row = []
        for day in week:
            key = day.isoformat()
            row.append(
                {
                    "num": day.day,
                    "in_month": day.month == shown.month,
                    "today": day == today,
                    "selected": selected is not None and day == selected,
                    "in_week": key in week_days,
                    "href": click(day),
                }
            )
        weeks.append(row)
    return {
        "label": shown.strftime("%B %Y"),
        "weeks": weeks,
        "prev_url": month_nav(prev_shown.isoformat()[:7]),
        "next_url": month_nav(next_shown.isoformat()[:7]),
        "weekdays": ["S", "M", "T", "W", "T", "F", "S"],
    }


def _sunday(day: date) -> date:
    return day - timedelta(days=(day.weekday() + 1) % 7)


@app.get("/week", response_class=HTMLResponse)
def week_view(
    request: Request,
    start: str | None = None,
    cal: str | None = None,
    channel: str | None = None,
    dept: str | None = None,
    org: str | None = None,
    q: str | None = None,
    cat: str | None = None,
):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=302)
    today = today_local()
    try:
        pivot = date.fromisoformat(start) if start else today
    except ValueError:
        pivot = today
    week_start = _sunday(pivot)
    week_end = week_start + timedelta(days=6)
    prev_start = (week_start - timedelta(days=7)).isoformat()
    next_start = (week_start + timedelta(days=7)).isoformat()
    after = _after_param(request, default="now")
    now = now_local()
    channels = _query_list(request, "channel")
    depts = _query_list(request, "dept")
    cats = _query_list(request, "cat")
    units = _query_list(request, "unit")
    orgs = _query_list(request, "org") or ([org] if org else [])
    raw = events_for_range(week_start.isoformat(), week_end.isoformat(), q=q or None)
    facets = facet_options(apply_filters(list(raw)), full=True)
    events = apply_filters(
        list(raw),
        channel=channels,
        dept=depts,
        org=orgs,
        cat=cats,
        unit=units,
    )
    events = filter_by_time(events, after, now=now, tz=TZINFO)
    by_day: dict[str, list] = {}
    for event in events:
        key = (event.get("start") or "")[:10]
        by_day.setdefault(key, []).append(event)
    columns = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        key = day.isoformat()
        items = _timed_first(by_day.get(key) or [])
        # A busy day had ~90 events, turning each column into an endless
        # scroll; show a readable slice and link the rest to the day view.
        columns.append(
            {
                "date": key,
                "label": day.strftime("%a"),
                "long": day.strftime("%b %-d"),
                "today": day == today,
                "events": items[:WEEK_COLUMN_LIMIT],
                "count": len(items),
                "more": max(0, len(items) - WEEK_COLUMN_LIMIT),
            }
        )
    shown = _parse_month(cal, week_start)
    state = {
        "start": week_start.isoformat(),
        "cal": shown.isoformat()[:7],
        "channel": channels,
        "dept": depts,
        "org": orgs[0] if len(orgs) == 1 else "",
        "q": q or "",
        "cat": cats,
        "unit": units,
        "after": after,
    }
    href, toggle = _filter_href("/week", state)

    mini = build_mini_month(
        shown,
        today,
        selected=week_start,
        week_start=week_start,
        click=lambda d: href(start=d.isoformat(), cal=d.isoformat()[:7]),
        month_nav=lambda m: href(cal=m),
    )

    return templates.TemplateResponse(
        request,
        "week.html",
        {
            **state,
            "week_label": f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d, %Y')}",
            "prev_start": prev_start,
            "next_start": next_start,
            "columns": columns,
            "facets": facets,
            "count": len(events),
            "total": len(raw),
            "notice": request.query_params.get("notice"),
            "href": href,
            "toggle": toggle,
            "mini": mini,
            **_time_ctx(after, now),
        },
    )


@app.get("/calendar", response_class=HTMLResponse)
def calendar_view(
    request: Request,
    month: str | None = None,
    channel: str | None = None,
    dept: str | None = None,
    org: str | None = None,
    q: str | None = None,
    cat: str | None = None,
):
    if not _logged_in(request):
        return RedirectResponse("/login", status_code=302)
    today = today_local()
    current = None
    if month and len(month) == 7:
        try:
            current = date(int(month[:4]), int(month[5:7]), 1)
        except ValueError:
            current = None
    if current is None:
        current = date(today.year, today.month, 1)
        month = current.isoformat()[:7]
    last = date(current.year + (current.month == 12), current.month % 12 + 1, 1) - timedelta(days=1)
    prev_month = (current - timedelta(days=1)).isoformat()[:7]
    next_month = (last + timedelta(days=1)).isoformat()[:7]
    after = _after_param(request, default="now")
    now = now_local()
    channels = _query_list(request, "channel")
    depts = _query_list(request, "dept")
    cats = _query_list(request, "cat")
    units = _query_list(request, "unit")
    orgs = _query_list(request, "org") or ([org] if org else [])
    raw = events_for_range(current.isoformat(), last.isoformat(), q=q or None)
    facets = facet_options(apply_filters(list(raw)), full=True)
    events = apply_filters(
        list(raw),
        channel=channels,
        dept=depts,
        org=orgs,
        cat=cats,
        unit=units,
    )
    events = filter_by_time(events, after, now=now, tz=TZINFO)
    by_day: dict[str, list] = {}
    for event in events:
        key = (event.get("start") or "")[:10]
        by_day.setdefault(key, []).append(event)
    weeks = []
    for week in _month_weeks(current.year, current.month):
        cells = []
        for day in week:
            key = day.isoformat()
            items = _timed_first(by_day.get(key) or [])
            cells.append(
                {
                    "date": key,
                    "num": day.day,
                    "in_month": day.month == current.month,
                    "today": day == today,
                    "count": len(items),
                    "events": items[:4],
                    "more": max(0, len(items) - 4),
                }
            )
        weeks.append(cells)
    state = {
        "month": month,
        "channel": channels,
        "dept": depts,
        "org": orgs[0] if len(orgs) == 1 else "",
        "q": q or "",
        "cat": cats,
        "unit": units,
        "after": after,
    }
    href, toggle = _filter_href("/calendar", state)

    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            **state,
            "month_label": current.strftime("%B %Y"),
            "prev_month": prev_month,
            "next_month": next_month,
            "weeks": weeks,
            "facets": facets,
            "count": len(events),
            "total": len(raw),
            "notice": request.query_params.get("notice"),
            "href": href,
            "toggle": toggle,
            **_time_ctx(after, now),
            "weekday_labels": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        },
    )
