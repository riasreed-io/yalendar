"""Signed-in access to Yale Connect and SOM Campus Groups.

Replaces the old timed auto-fill flow, which had two problems:

1. It raced. _on_host() treated the landing URL (…/home_login) as proof of
   being signed in, so if CAS had not redirected within a hard-coded 1.2s
   the script decided it was already authenticated, skipped the Duo wait
   and closed the window before you could type.
2. It never saved the session, so every run needed Duo again.

This module instead uses a persistent browser profile, so Duo happens once
and later runs reuse the cookies, and it waits on you rather than a timer.
Authentication is proven by calling the platform's own API and checking it
returns rows, not by pattern-matching a URL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import CONNECT_STATUS_PATH, DATA_DIR, mode, signin_allowed
from .connect import CONNECT_LIST, CONNECT_ORIGIN, SOM_LIST, SOM_ORIGIN, events_from_rows

def _require_personal_mode() -> None:
    """Signing in is a personal-machine operation, always.

    The demo and public builds are shared with people who are not me. A
    saved Yale session on either of them would let every visitor browse
    campus as its owner, so the code refuses rather than relying on nobody
    thinking to run the command.
    """
    if not signin_allowed():
        raise RuntimeError(
            f"Signing in is disabled in {mode()} mode. A saved Yale session "
            "belongs on one person's own machine and nowhere else. Run this "
            "with YALENDAR_MODE unset (or =personal)."
        )


PROFILE_DIR = DATA_DIR / "browser_profile"
# The login cookie is a *session* cookie, which Chrome discards when the
# browser closes - a persistent profile keeps the load-balancer and analytics
# cookies but loses the one that matters. storage_state() serialises session
# cookies too, so that is what actually carries a sign-in between processes.
STATE_PATH = DATA_DIR / "session_state.json"


@dataclass
class Platform:
    name: str
    source: str
    home: str
    host: str
    list_url: str
    origin: str


PLATFORMS: list[Platform] = [
    Platform("Yale Connect", "yale_connect", "https://yaleconnect.yale.edu/home_login",
             "yaleconnect.yale.edu", CONNECT_LIST, CONNECT_ORIGIN),
    Platform("Campus Groups (SOM)", "campus_groups", "https://groups.som.yale.edu/home_login",
             "groups.som.yale.edu", SOM_LIST, SOM_ORIGIN),
]


@dataclass
class PlatformCheck:
    name: str
    source: str
    signed_in: bool = False
    rows: int = 0
    private_rows: int = 0
    detail: str = ""


@dataclass
class SessionReport:
    checks: list[PlatformCheck] = field(default_factory=list)
    profile: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.signed_in for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "profile": self.profile,
            "platforms": {
                c.source: {
                    "name": c.name,
                    "signed_in": c.signed_in,
                    "rows": c.rows,
                    "private_rows": c.private_rows,
                    "detail": c.detail,
                }
                for c in self.checks
            },
        }


def _probe(page, platform: Platform) -> PlatformCheck:
    """Decide whether this browser is actually authenticated.

    Row count is NOT evidence: the mobile_ws endpoint happily serves events
    to anonymous callers, it just redacts the venue. The reliable signal is
    the page itself - signed out renders a "Login" page with login links and
    no logout link. Sign-in-only venue placeholders are then reported as a
    quality measure, since clearing them is the point of signing in.
    """
    check = PlatformCheck(name=platform.name, source=platform.source)

    try:
        logout_links = page.locator("a[href*='logout'], a[href*='signout']").count()
        login_links = page.locator("a[href*='login_only'], a[href*='/auth/login']").count()
        title = (page.title() or "").strip().lower()
    except Exception as exc:
        check.detail = f"page probe failed: {exc.__class__.__name__}"
        return check

    # Signed in is either an explicit logout link, or - since these sites put
    # logout behind a JS menu - landing on a real page with no login links
    # left. Signed out always renders a page titled "Login".
    # A CAS or Duo page is mid-handshake, not a destination: it has no login
    # links and is not titled "Login", so it would otherwise read as success.
    url = (page.url or "").lower()
    in_handshake = (
        "central authentication" in title
        or "duo" in title
        or "/cas" in url
        or "duosecurity" in url
        or "auth.yale.edu" in url
        or "secure.its.yale.edu" in url
    )
    check.signed_in = (
        not in_handshake
        and (logout_links > 0 or (title != "login" and login_links == 0))
    )

    try:
        response = page.request.get(f"{platform.list_url}?range=0&limit=50", timeout=30000)
        rows = response.json() if response.ok else []
        if not isinstance(rows, list):
            rows = rows.get("events") or rows.get("data") or []
    except Exception:
        rows = []
    check.rows = len(rows)
    check.private_rows = sum(
        1 for row in rows
        if "sign in to" in json.dumps(row).lower() or "private location" in json.dumps(row).lower()
    )

    if check.signed_in:
        check.detail = f"signed in (page={title[:38]!r})"
        if check.private_rows:
            check.detail += f"; {check.private_rows} venues still hidden"
    else:
        check.detail = (
            "still on the CAS/Duo handshake" if in_handshake else
            f"signed out (title={title!r}, {login_links} login links, "
            f"{logout_links} logout links)"
        )
    return check


def check_session(headed: bool = False) -> SessionReport:
    """Verify the saved sign-in still works, in a fresh browser."""
    _require_personal_mode()
    from playwright.sync_api import sync_playwright

    report = SessionReport(profile=str(STATE_PATH))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                storage_state=str(STATE_PATH) if STATE_PATH.is_file() else None,
            )
            page = context.new_page()
            for platform in PLATFORMS:
                page.goto(platform.home, wait_until="domcontentloaded", timeout=60000)
                report.checks.append(_probe(page, platform))
            context.close()
        finally:
            browser.close()
    CONNECT_STATUS_PATH.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report


def interactive_login(wait_seconds: int = 900, poll_seconds: float = 3.0) -> SessionReport:
    """Open a real browser and watch for you to sign in.

    Nothing to press. The script polls the platform until it sees an
    authenticated session, so finishing Duo is the only step - there is no
    keypress to miss and no countdown to lose. Credentials are never read,
    typed or stored by this code.
    """
    _require_personal_mode()
    import time

    from playwright.sync_api import sync_playwright

    report = SessionReport(profile=str(STATE_PATH))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            storage_state=str(STATE_PATH) if STATE_PATH.is_file() else None,
        )
        try:
            page = context.new_page()
            for platform in PLATFORMS:
                print(f"\n{'=' * 64}\n{platform.name}\n{'=' * 64}", flush=True)
                page.goto(platform.home, wait_until="domcontentloaded", timeout=60000)

                check = _probe(page, platform)
                if check.signed_in:
                    print(f"  Already signed in ({check.rows} events visible).", flush=True)
                    report.checks.append(check)
                    continue

                print("  Sign in in the browser window. Approve Duo on your phone.", flush=True)
                print("  Nothing to press here - this detects it automatically.", flush=True)

                deadline = time.time() + wait_seconds
                announced = 0
                while time.time() < deadline:
                    time.sleep(poll_seconds)
                    try:
                        check = _probe(page, platform)
                    except Exception:
                        continue
                    if check.signed_in:
                        break
                    waited = int(wait_seconds - (deadline - time.time()))
                    if waited // 60 > announced:
                        announced = waited // 60
                        print(f"  still waiting ({announced} min)...", flush=True)

                if check.signed_in:
                    print(f"  CONFIRMED: signed in. {check.rows} events visible"
                          f"{f', {check.private_rows} sign-in only' if check.private_rows else ''}.",
                          flush=True)
                else:
                    print(f"  Timed out after {wait_seconds // 60} min: {check.detail}", flush=True)
                report.checks.append(check)

            context.storage_state(path=str(STATE_PATH))
            print(f"\n  Session saved to {STATE_PATH.name}.", flush=True)
        finally:
            context.close()
            browser.close()

    CONNECT_STATUS_PATH.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report


def harvest(start_day: str = "", days: int = 0, month: str = "") -> tuple[list, SessionReport]:
    """Pull events using the saved session. Headless; no Duo if the profile is live."""
    _require_personal_mode()
    from playwright.sync_api import sync_playwright

    from . import db, dedupe

    report = SessionReport(profile=str(PROFILE_DIR))
    collected: list = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            storage_state=str(STATE_PATH) if STATE_PATH.is_file() else None,
        )
        try:
            page = context.new_page()
            for platform in PLATFORMS:
                page.goto(platform.home, wait_until="domcontentloaded", timeout=60000)
                check = _probe(page, platform)
                report.checks.append(check)
                if not check.signed_in:
                    db.record_source_run(
                        platform.source, 0, label=f"{platform.name} (signed in)",
                        status="error", detail="session expired - run `login` again",
                        authenticated=True)
                    continue

                offset = 0
                found_any = 0
                while offset < 1200:
                    response = page.request.get(
                        f"{platform.list_url}?range={offset}&limit=50", timeout=30000)
                    if not response.ok:
                        break
                    try:
                        rows = response.json()
                    except Exception:
                        break
                    batch, found = events_from_rows(
                        rows, source=platform.source, origin=platform.origin)
                    if month:
                        batch = [e for e in batch
                                 if (getattr(e, "start", None) or "").startswith(month)]
                    collected.extend(batch)
                    found_any += len(batch)
                    if not found:
                        break
                    offset += 50
                check.detail = f"pulled {found_any}"
                db.record_source_run(
                    platform.source, found_any,
                    label=f"{platform.name} (signed in)", status="ok",
                    detail=f"{check.private_rows} venues still hidden"
                            if check.private_rows else "all venues visible",
                    authenticated=True)
            # Refresh the saved cookies so the session keeps rolling forward.
            context.storage_state(path=str(STATE_PATH))
        finally:
            context.close()
            browser.close()

    if collected:
        db.upsert_events(collected)
        dedupe.apply_dedupe()
    CONNECT_STATUS_PATH.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return collected, report
