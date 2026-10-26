from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("YALE_TODAY_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------- run mode
#
# Yalendar was built as one person's local tool, which is why a single
# SQLite file and a single saved Yale session were enough. Sharing it needs
# that assumption named rather than assumed, so there are three modes and
# everything that touches the network, the disk or a credential asks which
# one is running.
#
#   personal  your own machine. Your sign-in, your database, live network.
#             The default, and the only mode that may hold a Yale session.
#   demo      the read-only snapshot shipped in demo/. No network, no
#             sign-in, no writes, and the clock is pinned to the day the
#             snapshot was taken so every view is populated. This is what a
#             stranger or a grader opens.
#   public    a live deployment of the public sources only. Writes and
#             refreshes are allowed; signing in is not.
#
MODES = ("personal", "demo", "public")
MODE = (os.environ.get("YALENDAR_MODE") or "personal").strip().lower()
if MODE not in MODES:
    MODE = "personal"

# Overridable so a different snapshot can be served without a rebuild --
# and so the test that proves the clock follows the snapshot can point at
# one with a date that is not today.
DEMO_DIR = Path(os.environ.get("YALENDAR_DEMO_DIR", ROOT / "demo"))
DEMO_SNAPSHOT = DEMO_DIR / "snapshot.json.gz"
DEMO_META = DEMO_DIR / "snapshot.meta.json"

# A separate file, so demo mode cannot read the personal database even by
# accident -- the isolation is a different path, not a careful code review.
DB_PATH = DATA_DIR / ("demo_events.db" if MODE == "demo" else "events.db")

PASSWORD_PATH = DATA_DIR / "dashboard_password.txt"
CONNECT_FEEDS_PATH = DATA_DIR / "connect_feeds.json"
CONNECT_STATUS_PATH = DATA_DIR / "connect_login_status.json"
EXTRA_ICS_PATH = DATA_DIR / "extra_ics.txt"

# The two files that carry a live Yale sign-in. Named once, here, so the
# deploy guard, the tests and the mode check all mean the same thing by it.
SESSION_STATE_PATH = DATA_DIR / "session_state.json"
BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"

TZ = "America/New_York"
TZINFO = ZoneInfo(TZ)


def mode() -> str:
    """The active mode, read through a call so messages and guards agree
    even when it is patched in a test."""
    return MODE


def is_demo() -> bool:
    return MODE == "demo"


def writes_allowed() -> bool:
    """Demo mode serves a frozen snapshot; nothing may change it."""
    return MODE != "demo"


def network_allowed() -> bool:
    """Whether this process may go out and fetch events."""
    return MODE != "demo"


def signin_allowed() -> bool:
    """Only your own machine may hold your Yale session."""
    return MODE == "personal"


def personal_files_present() -> list[Path]:
    """Any file here means this process can see somebody's Yale sign-in."""
    return [p for p in (SESSION_STATE_PATH, BROWSER_PROFILE_DIR) if p.exists()]


_demo_meta_cache: dict | None = None


def demo_meta() -> dict:
    """Snapshot provenance: when it was taken, how many events, from where."""
    global _demo_meta_cache
    if _demo_meta_cache is None:
        try:
            _demo_meta_cache = json.loads(DEMO_META.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _demo_meta_cache = {}
    return _demo_meta_cache


def now_local() -> datetime:
    """Current time on campus, regardless of the host's clock (Fly runs UTC).

    In demo mode this is the moment the snapshot was taken. A frozen set of
    events against a moving clock empties out within days and makes the app
    look broken; pinning the clock keeps every view populated, and the
    banner says plainly which day you are looking at.
    """
    if MODE == "demo":
        stamp = demo_meta().get("as_of")
        if stamp:
            try:
                return datetime.fromisoformat(stamp).astimezone(TZINFO)
            except ValueError:
                pass
    return datetime.now(TZINFO)


def today_local() -> date:
    return now_local().date()


USER_AGENT = "yale-today/0.1 (personal campus aggregator; local use)"
WINDOW_DAYS = 31
SHARED_INVITE = "Bulldog"

DEFAULT_NETID_PDF = Path(
    os.environ.get(
        "YALE_NETID_PDF",
        "/Users/rias/Downloads/Yale Calendar/Yale Net ID Info.pdf",
    )
)
