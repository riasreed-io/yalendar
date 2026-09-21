from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("YALE_TODAY_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "events.db"
PASSWORD_PATH = DATA_DIR / "dashboard_password.txt"
CONNECT_FEEDS_PATH = DATA_DIR / "connect_feeds.json"
CONNECT_STATUS_PATH = DATA_DIR / "connect_login_status.json"
EXTRA_ICS_PATH = DATA_DIR / "extra_ics.txt"

TZ = "America/New_York"
TZINFO = ZoneInfo(TZ)


def now_local() -> datetime:
    """Current time on campus, regardless of the host's clock (Fly runs UTC)."""
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
