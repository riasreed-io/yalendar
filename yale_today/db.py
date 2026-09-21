from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import DB_PATH
from .models import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT,
    all_day INTEGER NOT NULL DEFAULT 0,
    location TEXT,
    description TEXT,
    url TEXT,
    host TEXT,
    tags TEXT,
    fingerprint TEXT NOT NULL,
    canonical_id TEXT,
    extra_json TEXT,
    ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_start ON events(start);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_fingerprint ON events(fingerprint);
CREATE INDEX IF NOT EXISTS idx_events_canonical ON events(canonical_id);

CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'ics',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invites (
    token TEXT PRIMARY KEY,
    created_by TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visitors (
    email TEXT PRIMARY KEY,
    last_seen TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def upsert_events(events: list[Event], path: Path | None = None) -> int:
    if not events:
        return 0
    con = connect(path)
    count = 0
    with con:
        for event in events:
            row = event.as_row()
            extra = json.dumps(row.pop("extra_json") or {})
            con.execute(
                """
                INSERT INTO events (
                    id, source, source_id, title, start, "end", all_day,
                    location, description, url, host, tags, fingerprint,
                    canonical_id, extra_json
                ) VALUES (
                    :id, :source, :source_id, :title, :start, :end, :all_day,
                    :location, :description, :url, :host, :tags, :fingerprint,
                    :canonical_id, :extra_json
                )
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    start=excluded.start,
                    "end"=excluded."end",
                    all_day=excluded.all_day,
                    location=excluded.location,
                    description=excluded.description,
                    url=excluded.url,
                    host=excluded.host,
                    tags=excluded.tags,
                    fingerprint=excluded.fingerprint,
                    extra_json=excluded.extra_json
                """,
                {**row, "extra_json": extra},
            )
            count += 1
    con.close()
    return count


def keep_month(month: str, path: Path | None = None) -> int:
    prefix = (month or "").strip()
    if len(prefix) != 7:
        return 0
    con = connect(path)
    with con:
        deleted = con.execute(
            "DELETE FROM events WHERE start NOT LIKE ?",
            (f"{prefix}%",),
        ).rowcount
    con.close()
    return deleted


def list_feeds(path: Path | None = None) -> list[sqlite3.Row]:
    con = connect(path)
    rows = con.execute("SELECT * FROM feeds ORDER BY id").fetchall()
    con.close()
    return rows


def add_feed(url: str, label: str = "", source: str = "ics", path: Path | None = None) -> None:
    url = url.strip()
    if not url:
        return
    con = connect(path)
    with con:
        con.execute(
            "INSERT OR IGNORE INTO feeds (label, url, source) VALUES (?, ?, ?)",
            (label.strip(), url, source),
        )
    con.close()


def create_invite(created_by: str, path: Path | None = None) -> str:
    import secrets
    from datetime import datetime, timezone

    token = secrets.token_urlsafe(10)
    con = connect(path)
    with con:
        con.execute(
            "INSERT INTO invites (token, created_by, created_at) VALUES (?, ?, ?)",
            (token, created_by.strip().lower(), datetime.now(timezone.utc).isoformat()),
        )
    con.close()
    return token


def ensure_shared_invite(path: Path | None = None) -> None:
    from datetime import datetime, timezone

    from .config import SHARED_INVITE

    con = connect(path)
    with con:
        con.execute(
            "INSERT OR IGNORE INTO invites (token, created_by, created_at) VALUES (?, ?, ?)",
            (SHARED_INVITE, "yale-today", datetime.now(timezone.utc).isoformat()),
        )
    con.close()


def invite_ok(token: str, path: Path | None = None) -> bool:
    from .config import SHARED_INVITE

    token = (token or "").strip()
    if not token:
        return False
    if token.casefold() == SHARED_INVITE.casefold():
        return True
    return invite_exists(token, path)


def invite_exists(token: str, path: Path | None = None) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    con = connect(path)
    row = con.execute("SELECT token FROM invites WHERE token = ?", (token,)).fetchone()
    con.close()
    return bool(row)


def list_invites(path: Path | None = None) -> list[sqlite3.Row]:
    con = connect(path)
    rows = con.execute("SELECT * FROM invites ORDER BY created_at DESC").fetchall()
    con.close()
    return rows


def touch_visitor(email: str, path: Path | None = None) -> None:
    from datetime import datetime, timezone

    email = email.strip().lower()
    if not email:
        return
    con = connect(path)
    with con:
        con.execute(
            """
            INSERT INTO visitors (email, last_seen) VALUES (?, ?)
            ON CONFLICT(email) DO UPDATE SET last_seen = excluded.last_seen
            """,
            (email, datetime.now(timezone.utc).isoformat()),
        )
    con.close()


def list_visitors(path: Path | None = None) -> list[sqlite3.Row]:
    con = connect(path)
    rows = con.execute("SELECT * FROM visitors ORDER BY last_seen DESC").fetchall()
    con.close()
    return rows


def replace_feeds(urls: list[str], path: Path | None = None) -> None:
    con = connect(path)
    with con:
        con.execute("DELETE FROM feeds")
        for url in urls:
            url = url.strip()
            if url:
                con.execute(
                    "INSERT OR IGNORE INTO feeds (label, url, source) VALUES (?, ?, ?)",
                    ("", url, "ics"),
                )
    con.close()
