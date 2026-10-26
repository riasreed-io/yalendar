"""The shipped demo snapshot: a frozen, public-only copy of the calendar.

Why a snapshot and not a live deployment.

Yalendar's richest sources need a Yale sign-in, and the only sign-in it has
ever had is mine. Putting that session on a server to make the app shareable
would mean every visitor browsing campus with my credentials, and any private
club event I can see would become public. So the shared build gets a copy of
the data that an anonymous visitor could have fetched for themselves, and
nothing else.

That constraint is enforced by how the snapshot is *built*, not by filtering
afterwards: `scripts/make_demo.py` runs a normal ingest in a scratch data
directory with no session file in it, so the result is public by
construction. A filter over the live database would depend on me correctly
guessing which rows were private.

The snapshot is gzipped JSON rather than a SQLite file because it has to
survive a schema change -- a .db committed today stops opening the moment a
column is added, and the whole point is that someone can clone this in six
months and have it work.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import DB_PATH, DEMO_SNAPSHOT, TZINFO

SNAPSHOT_VERSION = 1

# Columns copied verbatim. Listed rather than SELECT *, so a column added
# later is an explicit decision instead of silently riding along.
EVENT_COLUMNS = (
    "id", "source", "source_id", "title", "start", "end", "all_day",
    "location", "description", "url", "host", "tags", "fingerprint",
    "canonical_id", "extra_json",
)
RUN_COLUMNS = (
    "source", "label", "event_count", "status", "detail", "authenticated", "ran_at",
)


def export(src_db: Path, out: Path = DEMO_SNAPSHOT, *, as_of: str = "",
           note: str = "", meta_out: Path | None = None) -> dict:
    """Write a snapshot of src_db to out, plus a small plain-text sidecar.

    The sidecar sits beside `out`, never at a fixed path: writing it to the
    committed location while the archive went somewhere else let a test
    exporting to a temp directory silently overwrite the real snapshot's
    metadata with zeroes.
    """
    con = sqlite3.connect(src_db)
    con.row_factory = sqlite3.Row
    cols = ", ".join(f'"{c}"' for c in EVENT_COLUMNS)
    events = [dict(r) for r in con.execute(f"SELECT {cols} FROM events ORDER BY start")]
    runs = [
        dict(r)
        for r in con.execute(
            f"SELECT {', '.join(RUN_COLUMNS)} FROM source_runs ORDER BY id"
        )
    ]
    con.close()

    authed = sorted({r["source"] for r in runs if r["authenticated"]})
    if authed:
        raise RuntimeError(
            "refusing to build a demo snapshot from a database that holds "
            f"signed-in pulls: {', '.join(authed)}. Build it with "
            "scripts/make_demo.py, which ingests into a scratch directory "
            "with no Yale session present."
        )

    starts = [e["start"][:10] for e in events if e.get("start")]
    meta = {
        "version": SNAPSHOT_VERSION,
        "as_of": as_of or datetime.now(TZINFO).isoformat(timespec="seconds"),
        "built_at": datetime.now(TZINFO).isoformat(timespec="seconds"),
        "events": len(events),
        "sources": sorted({e["source"] for e in events}),
        "first_date": min(starts) if starts else "",
        "last_date": max(starts) if starts else "",
        "note": note or "Public sources only. No signed-in data.",
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump({"meta": meta, "events": events, "source_runs": runs}, fh)
    sidecar = meta_out or (out.parent / "snapshot.meta.json")
    sidecar.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def load(path: Path = DEMO_SNAPSHOT) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def materialise(target: Path = DB_PATH, snapshot: Path = DEMO_SNAPSHOT) -> int:
    """Rebuild the demo database from the snapshot. Idempotent and cheap.

    Called at startup in demo mode. Rebuilding every boot rather than
    shipping a .db means the demo always matches the committed snapshot --
    nobody can leave a stale or hand-edited database on a volume and have it
    served as the demo.
    """
    if not snapshot.is_file():
        raise FileNotFoundError(
            f"No demo snapshot at {snapshot}. Build one with "
            "`python scripts/make_demo.py --rebuild`."
        )
    payload = load(snapshot)

    from .db import connect  # local import: db imports config, not demo

    target.parent.mkdir(parents=True, exist_ok=True)
    con = connect(target)
    cols = ", ".join(f'"{c}"' for c in EVENT_COLUMNS)
    marks = ", ".join("?" for _ in EVENT_COLUMNS)
    with con:
        con.execute("DELETE FROM events")
        con.execute("DELETE FROM source_runs")
        con.executemany(
            f"INSERT INTO events ({cols}) VALUES ({marks})",
            [tuple(e.get(c) for c in EVENT_COLUMNS) for e in payload["events"]],
        )
        con.executemany(
            f"INSERT INTO source_runs ({', '.join(RUN_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in RUN_COLUMNS)})",
            [tuple(r.get(c) for c in RUN_COLUMNS) for r in payload["source_runs"]],
        )
        con.execute(
            "INSERT INTO meta (key, value) VALUES ('demo_snapshot_built', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (payload["meta"].get("built_at", ""),),
        )
    con.close()
    return len(payload["events"])


def ensure(target: Path = DB_PATH, snapshot: Path = DEMO_SNAPSHOT) -> int:
    """Materialise the demo DB unless it already matches the snapshot."""
    from .config import demo_meta
    from .db import connect

    want = demo_meta().get("built_at", "")
    if target.is_file() and want:
        con = connect(target)
        row = con.execute(
            "SELECT value FROM meta WHERE key='demo_snapshot_built'"
        ).fetchone()
        count = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        con.close()
        if row and row[0] == want and count:
            return count
    return materialise(target, snapshot)
