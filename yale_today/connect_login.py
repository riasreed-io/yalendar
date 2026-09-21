from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

from .config import CONNECT_FEEDS_PATH, CONNECT_STATUS_PATH, DEFAULT_NETID_PDF
from .connect import CONNECT_LIST, SOM_LIST, SOM_ORIGIN, events_from_rows
from .credentials import CredentialError, load_netid_credentials

PLATFORMS = [
    {
        "name": "Yale Connect",
        "source": "yale_connect",
        "home": "https://yaleconnect.yale.edu/home_login",
        "host": "yaleconnect.yale.edu",
        "list": CONNECT_LIST,
        "origin": "https://yaleconnect.yale.edu",
    },
    {
        "name": "Campus Groups (SOM)",
        "source": "campus_groups",
        "home": "https://groups.som.yale.edu/home_login",
        "host": "groups.som.yale.edu",
        "list": SOM_LIST,
        "origin": SOM_ORIGIN,
    },
]


def _write_status(payload: dict) -> None:
    CONNECT_STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _on_host(url: str, host: str) -> bool:
    lower = url.lower()
    return host in lower and "cas" not in lower and "duo" not in lower


def _cas_fill(page, netid: str, password: str) -> None:
    user = page.locator("#username, input[name='username']").first
    user.wait_for(timeout=25000)
    user.fill(netid)
    page.locator("#password, input[name='password']").first.fill(password)
    page.locator("input[name='submit'], input[type='submit'], button[type='submit']").first.click()
    page.wait_for_timeout(2000)


def _wait_for_host(page, host: str, seconds: int = 180) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if _on_host(page.url, host):
            return True
        print(f"Waiting for {host}… {page.url[:90]}", flush=True)
        page.wait_for_timeout(4000)
    return False


def _in_window(start: str, start_day: str, days: int) -> bool:
    if not start_day or not days:
        return True
    prefix = start[:10]
    if len(prefix) != 10:
        return False
    begin = date.fromisoformat(start_day)
    end = begin + timedelta(days=days)
    when = date.fromisoformat(prefix)
    return begin <= when < end


def _launch_browser(p, headed: bool):
    kwargs = {"headless": not headed}
    if headed:
        kwargs["args"] = ["--start-maximized"]
        try:
            return p.chromium.launch(channel="chrome", **kwargs)
        except Exception:
            pass
    return p.chromium.launch(**kwargs)


def _pull_events(page, platform: dict, month: str = "", start_day: str = "", days: int = 0) -> list:
    collected = []
    offset = 0
    while offset < 1200:
        response = page.request.get(f"{platform['list']}?range={offset}&limit=50", timeout=30000)
        if not response.ok:
            break
        try:
            rows = response.json()
        except Exception:
            break
        batch, found = events_from_rows(
            rows, source=platform["source"], origin=platform["origin"]
        )
        if month:
            batch = [e for e in batch if (getattr(e, "start", None) or "").startswith(month)]
        elif start_day and days:
            batch = [
                e
                for e in batch
                if _in_window(getattr(e, "start", None) or "", start_day, days)
            ]
        collected.extend(batch)
        if not found:
            break
        offset += 50
    if collected:
        from . import db, dedupe

        db.upsert_events(collected)
        dedupe.apply_dedupe()
        print(f"Saved {len(collected)} {platform['name']} events.", flush=True)
    return collected


def login_and_capture_ics(
    pdf_path: Path | None = None,
    headed: bool = False,
    month: str = "",
    sources: list[str] | None = None,
    start_day: str = "",
    days: int = 0,
) -> dict:
    """Sign into Yale Connect and SOM Campus Groups. Never writes NetID/password."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed") from exc

    netid, password = "", ""
    if not headed:
        netid, password = load_netid_credentials(pdf_path or DEFAULT_NETID_PDF)
    result = {
        "ok": False,
        "needs_duo": False,
        "message": "",
        "ics_urls": [],
        "logged_in": False,
        "events": [],
        "event_count": 0,
        "platforms": {},
    }

    try:
        with sync_playwright() as p:
            print("Launching browser…", flush=True)
            if headed:
                print(
                    "A Chrome/Chromium window should appear. Sign in yourself, including Duo.",
                    flush=True,
                )
            browser = _launch_browser(p, headed)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            all_events = []
            logged = []

            for platform in PLATFORMS:
                if sources and platform["source"] not in sources:
                    continue
                print(f"Opening {platform['name']}…", flush=True)
                page.goto(platform["home"], wait_until="domcontentloaded", timeout=60000)
                if page.locator("a[href*='login']").count():
                    page.locator("a[href='/webapp/auth/login'], a[href*='login_only']").first.click()
                    page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(1200)

                if not _on_host(page.url, platform["host"]):
                    if headed:
                        result["needs_duo"] = True
                        print(
                            f"Log into {platform['name']} in that window. Approve Duo on your phone. "
                            "Waiting up to 10 minutes.",
                            flush=True,
                        )
                        if not _wait_for_host(page, platform["host"], seconds=600):
                            result["platforms"][platform["source"]] = "timeout"
                            continue
                    else:
                        if page.locator("#username, input[name='username']").count():
                            _cas_fill(page, netid, password)
                        html = page.content().lower()
                        if "duo" in html or "duosecurity" in page.url.lower():
                            result["needs_duo"] = True
                            print(
                                f"Approve Duo for {platform['name']}. Waiting up to 3 minutes.",
                                flush=True,
                            )
                        if not _wait_for_host(page, platform["host"]):
                            result["platforms"][platform["source"]] = "timeout"
                            continue

                if not _on_host(page.url, platform["host"]):
                    result["platforms"][platform["source"]] = f"not signed in ({page.url.split('?')[0]})"
                    continue

                events = _pull_events(
                    page, platform, month=month, start_day=start_day, days=days
                )
                all_events.extend(events)
                logged.append(platform["name"])
                result["platforms"][platform["source"]] = f"ok:{len(events)}"

            result["events"] = all_events
            result["event_count"] = len(all_events)
            result["logged_in"] = bool(logged)
            result["ok"] = bool(logged)
            result["message"] = (
                f"Signed into {', '.join(logged) or 'neither'}. Pulled {len(all_events)} events."
            )
            CONNECT_FEEDS_PATH.write_text(json.dumps({"ics_urls": []}, indent=2), encoding="utf-8")
            browser.close()
    except CredentialError as exc:
        result["message"] = str(exc)
    except Exception as exc:
        result["message"] = f"Login failed: {exc.__class__.__name__}: {exc}"
    finally:
        netid = ""
        password = ""

    status = {k: v for k, v in result.items() if k not in {"ics_urls", "events"}}
    _write_status(status)
    return result
